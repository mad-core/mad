# Requirements — Mad infra

## Goal

Build the first functional version of Mad: a REST API that accepts a JSON describing an agent and a set of resources, provisions a local workspace, clones the indicated GitHub repositories, and runs an autonomous Claude session against them.

## Functional requirements

### FR-1 — Create session
The system MUST accept `POST /v1/sessions` with a JSON body describing the agent and its resources, and return a `session_id` plus the list of mounted resources.

### FR-2 — Resource provisioning
For each resource in the request:
- `type=github_repository`: clone the repo using the provided `authorization_token` into the mapped `mount_path`.
- `type=file`: write the given `content` string to the mapped `mount_path`.

After cloning, GitHub tokens MUST be removed from the git remote URL so they never remain in the workspace.

### FR-3 — Path isolation
The `mount_path` declared in the request is mapped to a subdirectory inside the session workspace. Absolute paths outside the workspace MUST be rejected (path traversal prevention).

### FR-4 — Session messaging
The client MUST be able to send `user.message` events to a running session via `POST /v1/sessions/{id}/events`. The first such message starts the agent loop.

### FR-5 — Event streaming
The client MUST be able to subscribe to a real-time stream of session events via `GET /v1/sessions/{id}/stream` using Server-Sent Events.

### FR-6 — Agent loop
After receiving the first `user.message`, the harness MUST run the agent loop in the background (non-blocking) until Claude finishes, asks for human help, or hits an error. Each step MUST be recorded in the session log.

### FR-7 — Persistence and recovery
The session log MUST be the source of truth: an append-only JSONL file per session. If the process crashes, a new harness instance MUST be able to read the log and resume from the last event.

### FR-8 — Session lifecycle endpoints
The API MUST expose endpoints to inspect the current state of a session, list all sessions, and delete a session (freeing its temporary workspace while preserving its log as historical record).

### FR-9 — Idempotent creation
`POST /v1/sessions` MUST accept an optional `Idempotency-Key` header. Repeated requests with the same key MUST return the already-created session instead of cloning the repos a second time.

### FR-10 — LLM providers
The system MUST support two providers, selectable via `agent.provider`:
- `claude_cli`: runs `claude --print --output-format stream-json` headless. For Pro/Max accounts.
- `anthropic_api`: calls the Anthropic SDK directly. Requires `ANTHROPIC_API_KEY`.

### FR-11 — Native tool use
Tool calls MUST use Anthropic's native structured tool use (SDK `tools=[...]` with JSON schema, or `stream-json` from the CLI). The harness MUST NOT parse tool calls from free-text with regex. Any tool call emitted as free text is ignored.

## Non-functional constraints

- **NFR-1 — Package layout.** Core logic lives in the `mad` package under `src/mad/`, split by concern: `mad.api` (FastAPI app + routes), `mad.core` (session log, workspace, security), `mad.agent` (harness loop + tools), `mad.providers` (`LLMProvider` implementations). No module-level mutable globals — state is held on a `SessionStore` injected via `create_app(store=...)`. The project stays `pip install -e .` compatible.
- **NFR-2 — Token hygiene.** GitHub tokens are used to clone and then stripped from the remote. They are never persisted to the workspace.
- **NFR-3 — Dual logging.** Every action is printed to stdout AND appended to the session log. The log is the source of truth.
- **NFR-4 — Environment preparation is out of scope.** The operator prepares the server's Python environment manually (`python -m venv .venv && pip install -r requirements.txt`). Mad does NOT install per-session packages. Any dependency the agent needs inside the workspace must already be available on the host, or the agent installs it as part of its work.
- **NFR-5 — Sandbox hardening is operator's responsibility.** The current implementation executes sandbox commands as subprocesses of the FastAPI process. Hardening via `bubblewrap` or similar is documented in [`../../docs/sandbox-bwrap.md`](../../docs/sandbox-bwrap.md) and left to the operator.

## MVP acceptance criteria

The MVP is done when you can:

1. `POST /v1/sessions` with a GitHub repo and see it cloned correctly in the workspace.
2. `POST /v1/sessions/{id}/events` with a `user.message` describing the work to perform.
3. `GET /v1/sessions/{id}/stream` and watch Claude explore the repo, make changes, and report the result in real time.
4. `GET /v1/sessions/{id}` and see the final state with every event recorded.
5. `GET /v1/sessions` and see the list of past sessions.
6. Resume a session by sending a new `user.message` to the same `session_id`.
7. `DELETE /v1/sessions/{id}` and verify the temporary workspace is cleaned up (the session log is preserved).
8. Resend `POST /v1/sessions` with the same `Idempotency-Key` and get the existing session back instead of a new one.
