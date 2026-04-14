# Implementation Plan — Mad v0.1

## Stack

```
Python 3.11+
FastAPI + uvicorn
sse-starlette          (for SSE)
subprocess             (for sandbox and Claude CLI)
json + pathlib         (for session log)
anthropic SDK          (optional, for the anthropic_api provider)
```

Dependencies live in the repo's `requirements.txt`. The operator prepares the environment manually:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Mad does NOT install per-session packages. Anything the agent needs inside the workspace must already be available on the host, or the agent installs it as part of its own work.

## Implementation rules

1. **FastAPI + uvicorn.** FastAPI as the framework, uvicorn to serve.

2. **One `app.py` file for the MVP.** Don't over-structure yet. The three components (session log, sandbox, harness) can be classes/functions inside the same file or split into simple sibling modules — but not before it hurts.

3. **Path mapping.** A `mount_path` like `/workspace/backend` is mapped to a subdirectory of the session workspace (e.g. `{workspace_dir}/workspace_backend`). Absolute paths that would escape the workspace MUST be rejected (path traversal prevention).

4. **Token hygiene.** GitHub tokens are used only for `git clone`, then stripped from the remote with `git remote set-url origin {url_without_token}`. They are never persisted to the workspace.

5. **SSE via `sse-starlette`.** The stream endpoint uses `EventSourceResponse` from `sse-starlette`. Every event appended to the session log is pushed to connected subscribers.

6. **Agent loop in background.** After the first `user.message`, the harness runs as an asyncio task. The endpoint returns immediately.

7. **Endpoints.** See [`api.md`](api.md) for the full contract. Minimum set:
   ```
   POST   /v1/sessions              (accepts Idempotency-Key header)
   POST   /v1/sessions/{id}/events
   GET    /v1/sessions/{id}/stream
   GET    /v1/sessions/{id}
   GET    /v1/sessions
   DELETE /v1/sessions/{id}
   ```

8. **LLM providers.**
   - `claude_cli`: runs `claude --print --output-format stream-json` as a subprocess. For Pro/Max accounts.
   - `anthropic_api`: uses the Anthropic SDK. Requires `ANTHROPIC_API_KEY`.
   - Selected via `agent.provider` in the request JSON.

9. **Native tool use only.** Tool calls are consumed via Anthropic's native structured tool use:
   - `anthropic_api`: pass tools as `tools=[...]` with their JSON schema; read `tool_use` blocks from the response; feed results back as `tool_result` blocks.
   - `claude_cli`: use `--output-format stream-json` to receive structured tool use events.
   - The harness NEVER parses tool calls from free text with regex. Any tool call emitted as free text is ignored.

10. **Dual logging.** Every action is printed to stdout AND appended to the JSONL session log. The session log is the source of truth.

## Out of scope for v0.1

The following are deliberately deferred. See [`../../docs/backlog.md`](../../docs/backlog.md) for rationale and proposed approaches:

- Separation of event log and projected state (SQLite + `state.json`).
- Harness running as a separate worker, crash-tolerant.
- Real pub/sub for the SSE stream (with `Last-Event-ID` support).
- Docker containers for the sandbox. Current version uses direct subprocess; there is a hardening guide using `bubblewrap` in [`../../docs/sandbox-bwrap.md`](../../docs/sandbox-bwrap.md) the operator can apply at their discretion.
- Encrypted vaults for credentials (tokens currently travel in the JSON and are not persisted).
- Automatic per-session package installation (`environment.packages`). The operator prepares the environment by hand with `venv` + `requirements.txt`.
- Multi-session workflows.
- Scheduler / cron.
- API authentication.
- Web dashboard.
- Additional LLM providers (Ollama, OpenAI, etc).
