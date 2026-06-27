---
service: mad
domain: backend
section: conventions
source_of_truth: repo
---

# Error Handling

Error taxonomy and how errors surface to callers: the domain exceptions and the
FastAPI exception handlers that map them to HTTP status codes / bodies.

Mad keeps error *meaning* in the framework-free core (`mad.core`, hard rule 4) and
error *translation* at the inbound boundary. Use cases raise plain Python
exceptions; the FastAPI app registers `@app.exception_handler(...)` callbacks in
`src/mad/adapters/inbound/http/app.py` that map each one to a status code and a
JSON body. The MCP adapter calls the **same** use cases (hard rule 13), so it
raises the **same** exceptions — they surface as MCP tool errors rather than HTTP
responses, but the taxonomy is identical.

## Where exceptions live

- `src/mad/core/sessions/domain/exceptions/base.py` — `DomainError` (base),
  `PathTraversalError`, `SessionNotFound`.
- `src/mad/core/orchestration/domain/exceptions/base.py` — `TaskNotFound`,
  `TaskAlreadyDispatched`, `SessionHasInFlightTask`.
- `src/mad/core/orchestration/domain/exceptions/workflow.py` — `InvalidWorkflow`,
  `WorkflowNotFound`.
- `src/mad/core/orchestration/domain/dispatch_policy.py` — `InvalidDispatchPolicy`
  (subclass of `ValueError`).
- `src/mad/core/orchestration/domain/ordering.py` — `InvalidPriority`
  (subclass of `ValueError`).
- `src/mad/core/orchestration/use_cases/list_provider_models.py` —
  `InvalidModelError` (subclass of `ValueError`).
- `src/mad/core/orchestration/use_cases/trigger_manual_dispatch.py` —
  `TriggerNotApplicable`.
- `src/mad/adapters/outbound/persistence/local_workspace_provisioner.py` —
  `MalformedSettingsLocalJson` (subclass of `ValueError`), `GitCloneError`.
- `src/mad/core/orchestration/domain/exceptions/rate_limit.py` — `RateLimitError`
  (launcher-internal; never reaches the HTTP boundary — see below).
- `src/mad/adapters/outbound/agents/claude_cli.py` — `ClaudeCLIError`
  (launcher-internal).

## HTTP exception handlers

All handlers are registered in `create_app(...)` and return
`JSONResponse(status_code=..., content={"detail": str(exc)})`. The body is always
the single-key shape `{"detail": "<message>"}`, matching FastAPI's default error
envelope so clients parse one shape everywhere.

| Exception | Meaning | HTTP status | Response body |
|---|---|---|---|
| `PathTraversalError` | A `mount_path` is not absolute or would escape the session workspace (hard rule 3); raised when constructing `MountPath` during session creation. | 400 | `{"detail": "invalid mount_path '<path>': <reason>"}` |
| `SessionNotFound` | The `session_id` is absent from the live index and the JSONL log; raised by get / delete / send-message / enqueue / cancel / trigger / list-tasks / policy use cases. | 404 | `{"detail": "Session '<id>' not found"}` |
| `ValueError` (generic) | Catch-all for invalid input that is not a more specific subclass — includes `MalformedSettingsLocalJson` (a repo ships unparseable `.claude/settings.local.json`) and the MCP `older_than is not valid` guard. | 400 | `{"detail": "<message>"}` |
| `TaskNotFound` | A `task_id` does not exist on the target session (cancel / inspect). | 404 | `{"detail": "task not found: <task_id>"}` |
| `TaskAlreadyDispatched` | A cancel was attempted on a task that is already running; v1 cannot cancel in-flight tasks (ADR-0009 Decision 6). | 409 | `{"detail": "task already dispatched: <task_id>"}` |
| `SessionHasInFlightTask` | `/messages` was called while a queued task is dispatched on that session; the two dispatch paths are mutually exclusive (ADR-0009 Decision 6). | 409 | `{"detail": "session <id> is running queued task <task_id>; wait or cancel via DELETE /tasks/<task_id>"}` |
| `InvalidDispatchPolicy` | A malformed dispatch-policy body (`policy_from_dict` rejection). Subclasses `ValueError` but is mapped to 422, not 400, because it is a defect in the caller's payload. | 422 | `{"detail": "<message>"}` |
| `InvalidPriority` | A priority outside `[MIN_PRIORITY, MAX_PRIORITY]` or a non-int; rejected loudly rather than silently clamped (issue #46). Subclasses `ValueError`, mapped to 422. | 422 | `{"detail": "priority must be ..."}` |
| `InvalidModelError` | The requested model is not in the provider's advertised catalog. Subclasses `ValueError`, mapped to 422. | 422 | `{"detail": "Model '<m>' is not available for provider '<p>'. Available: [...]"}` |
| `TriggerNotApplicable` | A manual dispatch trigger arrived for a session whose policy is not manual. | 409 | `{"detail": "manual trigger does not apply to session <id> with dispatch policy '<kind>'"}` |
| `GitCloneError` | The upstream repository clone failed (e.g. a private repo with no host credential). Upstream authentication / availability failures are distinguished from malformed requests. | 502 | `{"detail": "<message>"}` |
| `InvalidWorkflow` | A malformed workflow body: cyclic dependency graph, unknown `depends_on` reference, or dangling `from_step`. Subclasses `ValueError` but is mapped to 422, not 400, because it is a defect in the caller's payload (issue #90). | 422 | `{"detail": "<message>"}` |
| `WorkflowNotFound` | The `workflow_id` does not exist in the workflow read model. | 404 | `{"detail": "workflow not found: <workflow_id>"}` |

Handler-ordering note: `InvalidDispatchPolicy`, `InvalidPriority`, `InvalidModelError`,
and `InvalidWorkflow` all inherit from `ValueError`, which also has a generic
handler (400). FastAPI dispatches to the most specific registered handler, so
these four resolve to 422 while every other bare `ValueError` falls through to
the 400 handler. The 422 choice for these four is intentional and documented
inline in `app.py`: an out-of-range / unknown value, or a defect in a structural
payload, is a validation error distinct from a generic bad request.

## Automatic 422 from request validation (hard rule 9)

Every JSON route declares a Pydantic `BaseModel` for its body (and typed query
params / headers). When a request body fails schema validation — wrong type,
missing required field, out-of-range constrained value — FastAPI returns **422
Unprocessable Entity** automatically, before any use case runs, with a structured
`{"detail": [{"loc": ..., "msg": ..., "type": ...}, ...]}` body. This is the
first line of error defense and is why no route reads raw `request.json()` /
`dict[str, Any]` for the body. The custom 422 handlers above complement this for
semantic validation that Pydantic alone cannot express (e.g. a model name must
exist in a live provider catalog).

## Launcher-internal errors (do not reach the HTTP boundary)

Two exceptions are raised by `AgentLauncher` implementations and handled inside
the system rather than returned to a caller:

- `RateLimitError` — raised when the external agent exits due to API
  rate-limiting / overload. The dispatcher catches it specifically and drives the
  exponential-backoff retry loop (issue #62), carrying the captured
  `conversation_id` and an optional `retry_after_floor_s`. It is not mapped to an
  HTTP status; it changes scheduling, not the response.
- `ClaudeCLIError` — internal to the `claude_cli` launcher.

For all other agent failures (non-zero exit, timeout), the launcher does not raise
to the caller at all: per the `AgentLauncher` contract it emits a
`session.error` event onto the session event log (the source of truth, hard
rule 6) with scrubbed stderr, and `session.status_idle` on success. Operational
failures of a running agent are observed through the event stream
(`GET /v1/events/stream`), not through an HTTP error response on the request that
launched it.

## MCP parity

The MCP inbound adapter (`src/mad/adapters/inbound/mcp/server.py`) invokes the
same use cases with the same in-process dependencies (hard rule 13, ADR-0012), so
it raises the identical domain exceptions. MCP does not register the HTTP
`JSONResponse` handlers; instead the exceptions propagate out of the tool call and
the MCP runtime surfaces them as tool errors to the client. The error *taxonomy*
(what can go wrong and what it means) is therefore shared across both surfaces;
only the transport-level envelope differs.
