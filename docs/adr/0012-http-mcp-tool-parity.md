# ADR-0012 — Every request/response HTTP route is an MCP tool

- Status: Accepted
- Date: 2026-06-12
- Supersedes: ADR-0010 Decision 3 ("Five tools, ~1:1 with the session use cases — no event tools")

## Context

ADR-0010 mounted MCP as an HTTP-mounted inbound adapter and shipped **five** tools, deliberately scoped to the session lifecycle (`create` / `send_message` / `list` / `get` / `delete`). Orchestration (task queue, dispatch policy) and the event query were left off the MCP surface — ADR-0004 deferred event tools as "a non-actionable firehose," and ADR-0010 framed the five tools as a curated subset.

Two things changed that calculus:

1. **MCP is the primary surface, not a convenience.** In practice the operator drives Mad from an AI agent over MCP more than over raw HTTP. A capability that exists only on `/v1/...` and not as a tool is, in effect, invisible to the main consumer. The curated-subset stance silently amputated half the product (you could open a session over MCP but not schedule when its work runs).

2. **The subset drifts by omission.** When #45 added `GET`/`PUT /v1/dispatch_policy` and `DELETE /v1/sessions/{id}/dispatch_policy` as HTTP-only, nothing flagged that the MCP consumer couldn't reach them. "Which routes are tools" was tribal knowledge, not a contract — exactly the drift hard rule 9 exists to prevent, one level up (route-set parity, not just schema parity).

The forces from ADR-0010 still hold: tools call use cases in-process (Decision 2) and reuse the HTTP layer's Pydantic models (Decision 4). This ADR extends that discipline from *schema* parity to *surface* parity.

## Decision

### 1. One MCP tool per request/response HTTP route — full parity

Every JSON request/response route under `/v1` has exactly one corresponding tool in `src/mad/adapters/inbound/mcp/server.py`. The tool calls the same use case with the same in-process dependencies and returns the same Pydantic model as the HTTP handler — it carries no logic the route doesn't (ADR-0010 Decisions 2 and 4, unchanged). This is now **CLAUDE.md hard rule 13**.

Adding, changing, or removing an HTTP route requires the mirrored change to its tool in the same PR. The intake template and the `/work` pipeline carry the reminder so it is considered at ticket time, not discovered in review.

The fifteen tools at this ADR's acceptance: the original five plus `mad_cleanup_sessions`, `mad_enqueue_task`, `mad_list_tasks`, `mad_cancel_task`, `mad_set_session_dispatch_policy`, `mad_clear_session_dispatch_policy`, `mad_trigger_dispatch`, `mad_get_deployment_dispatch_policy`, `mad_set_deployment_dispatch_policy`, and `mad_query_events`.

### 2. The streaming SSE surface is the sole carve-out

`GET /v1/events/stream` is **not** mirrored as a tool. Server-sent events are a long-lived telemetry stream, not a request/response call; modelling them as a tool would mean an unbounded tool result, which is the wrong shape for an MCP tool and the firehose ADR-0004 warned about. The stream stays on MCP's own streaming surface. The **historical** query `GET /v1/events` is NOT exempt — bounded, paginated, request/response — it is `mad_query_events`.

The parity rule therefore reads: *every non-streaming request/response `/v1` route is a tool.*

### 3. Parity is enforced mechanically, not by reviewer vigilance

`tests/integration/api/test_http_mcp_parity.py` enumerates the live app's `/v1` routes and the MCP server's registered tools, and fails if any non-stream route has no mapped tool (or a mapped tool no longer exists). A new HTTP route makes the test red until its tool and mapping entry are added — the same forcing function the OpenAPI contract tests give the REST boundary.

### 4. No new commit scope

MCP tools are mounted inside the public FastAPI app (ADR-0010 Decision 1), so a tool added alongside its route ships under the same `feat(http)` / `fix(http)` commit as the route. No `mcp` scope is added to hard rule 12's closed set; the parity rule keeps the two halves in one commit by construction.

## Consequences

**Wins:**

- The MCP consumer can reach every actionable capability the REST API exposes — parity is a contract, not a curation.
- Route-set drift is caught by a test, not by whoever remembers MCP exists.
- The in-process + shared-model discipline (ADR-0010) means each new tool is ~15 lines and cannot diverge in schema.

**Costs:**

- Every new JSON route is now two edits (route + tool) and a parity-mapping entry. Accepted: that is the point — the cost is the guardrail.
- The MCP tool list is larger; an orchestrator sees fifteen tools instead of five. Tool descriptions carry the `Mirrors <METHOD> <path>` note so the mapping is legible.

**Revisit if:**

- A future route is genuinely streaming/long-lived (like the SSE stream). Such routes extend the carve-out; record them explicitly in the parity test's exclusion set with a one-line reason, never silently.
- MCP grows resources/prompts beyond tools. This ADR governs tools↔routes; a resource surface would get its own decision.

## Alternatives considered

- **Keep the curated five-tool subset (status quo).** Rejected: the primary consumer can't reach scheduling or the task queue, and "which routes are tools" stays tribal knowledge that drifts on every new route.
- **Generate tools from the OpenAPI spec at runtime.** Rejected for v1: attractive but couples tool ergonomics (names, descriptions, the SSE carve-out) to a generator, and the in-process use-case call (ADR-0010 Decision 2) is not derivable from OpenAPI. The parity *test* gives the safety net without the generator's complexity; revisit if the tool count makes hand-authoring a real burden.
- **Mirror the SSE stream as a tool too.** Rejected: an unbounded tool result is the wrong MCP shape and the firehose ADR-0004 already named. Streaming stays streaming.

## Cross-references

- [ADR-0010](0010-mcp-mounted-http-inbound-adapter.md) — MCP adapter; Decisions 1/2/4 stand, Decision 3 superseded here.
- [ADR-0004](0004-events-module-vocabulary-and-scope.md) — events are observability; the SSE carve-out preserves this for the *stream*, while the bounded query becomes a tool.
- CLAUDE.md hard rule 13 (parity), hard rule 9 (typed boundary), hard rule 1 (Mad infers nothing — tools return raw shapes).
