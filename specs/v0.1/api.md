# API Contract — Mad v0.1

Base path: `/v1`.
Content type: `application/json` unless otherwise noted.

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/sessions` | Create a session (clone repos, provision workspace). Accepts optional `Idempotency-Key` header. |
| `POST` | `/v1/sessions/{id}/events` | Send events (e.g. `user.message`) to a session. |
| `GET` | `/v1/sessions/{id}/stream` | Subscribe to the SSE event stream for a session. |
| `GET` | `/v1/sessions/{id}` | Current state of a session. |
| `GET` | `/v1/sessions` | List sessions. |
| `DELETE` | `/v1/sessions/{id}` | Close the session and clean up its temporary workspace. The session log is preserved as historical record. |

## `POST /v1/sessions`

Creates a new session, provisions its workspace, and clones the requested resources.

### Headers

- `Idempotency-Key: <uuid>` (optional). If the same key is replayed, the server returns the already-created session instead of cloning the repos again.

### Request body

```json
{
  "agent": {
    "name": "issue-solver",
    "model": "claude-sonnet-4-6",
    "system": "You are an autonomous developer agent. You receive tasks and implement solutions...",
    "provider": "claude_cli"
  },
  "resources": [
    {
      "type": "github_repository",
      "url": "https://github.com/org/backend",
      "mount_path": "/workspace/backend",
      "authorization_token": "ghp_xxx",
      "checkout": {
        "type": "branch",
        "name": "main"
      }
    },
    {
      "type": "github_repository",
      "url": "https://github.com/org/shared-types",
      "mount_path": "/workspace/types",
      "authorization_token": "ghp_xxx"
    },
    {
      "type": "file",
      "content": "contenido del archivo como string",
      "mount_path": "/workspace/data/input.csv"
    }
  ]
}
```

### Fields

**`agent`**
- `name` — free-form label for the agent role.
- `model` — Claude model id (e.g. `claude-sonnet-4-6`). Optional when using `claude_cli` (the CLI picks its own).
- `system` — system prompt for the agent.
- `provider` — one of `claude_cli` | `anthropic_api`.

**`resources[]`**
Each resource is one of:

- `github_repository`
  - `url` — HTTPS clone URL.
  - `mount_path` — canonical path the agent will see (e.g. `/workspace/backend`). Mapped to a subdirectory inside the session workspace.
  - `authorization_token` — GitHub token used for cloning. Stripped from the remote after clone.
  - `checkout` (optional) — `{ "type": "branch", "name": "..." }`. Defaults to the default branch.

- `file`
  - `content` — file content as a string.
  - `mount_path` — canonical path where the file will be written.

### Response

```json
{
  "session_id": "sesn_abc123",
  "status": "created",
  "workspace": "/tmp/mad_sesn_abc123",
  "resources_mounted": [
    {
      "type": "github_repository",
      "url": "https://github.com/org/backend",
      "mount_path": "/workspace/backend",
      "local_path": "/tmp/mad_sesn_abc123/workspace_backend",
      "status": "cloned"
    }
  ]
}
```

## `POST /v1/sessions/{id}/events`

Send one or more events to a running session. The first `user.message` event starts the agent loop.

```json
{
  "events": [
    {
      "type": "user.message",
      "content": "Resuelve el issue #42. El repo está en /workspace/backend."
    }
  ]
}
```

## `GET /v1/sessions/{id}/stream`

Server-Sent Events stream. Each session log event is pushed as one SSE `data:` frame.

```
GET /v1/sessions/{session_id}/stream
Accept: text/event-stream
```

Example frames:

```
data: {"type": "session.status_running", "timestamp": "..."}
data: {"type": "agent.message", "content": "Voy a explorar el repo...", "turn": 1}
data: {"type": "agent.tool_use", "tool": "bash", "input": "find /workspace/repo -name '*.py'"}
data: {"type": "agent.tool_result", "tool": "bash", "result": "src/auth.py\nsrc/utils.py"}
data: {"type": "session.status_idle", "stop_reason": "completed"}
```

## `GET /v1/sessions/{id}`

Returns the current state of a session plus the full event log (or a summary, depending on query params — to be detailed during implementation).

## `GET /v1/sessions`

Lists all sessions known to the server.

## `DELETE /v1/sessions/{id}`

Closes the session and removes its temporary workspace directory. The JSONL session log is preserved on disk as an immutable historical record.

## End-to-end example

```bash
# 1. Start the server
uvicorn app:app --host 0.0.0.0 --port 8000

# 2. Create a session
curl -X POST http://localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{
    "agent": {
      "name": "code-fixer",
      "system": "You are an autonomous developer. Fix issues and create PRs.",
      "provider": "claude_cli"
    },
    "resources": [
      {
        "type": "github_repository",
        "url": "https://github.com/myorg/myrepo",
        "mount_path": "/workspace/repo",
        "authorization_token": "ghp_xxx",
        "checkout": {"type": "branch", "name": "main"}
      }
    ]
  }'

# Response:
# {"session_id": "sesn_abc123", "status": "created", "resources_mounted": [...]}

# 3. Kick off the agent
curl -X POST http://localhost:8000/v1/sessions/sesn_abc123/events \
  -H "Content-Type: application/json" \
  -d '{
    "events": [{
      "type": "user.message",
      "content": "Resuelve el issue #15 del repo en /workspace/repo"
    }]
  }'

# 4. Listen to the event stream
curl -N http://localhost:8000/v1/sessions/sesn_abc123/stream
```
