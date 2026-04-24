# Design — Mad infra

## Overview

Mad is split into three decoupled components that together turn a JSON request into a running autonomous Claude session.

```
┌─────────────┐    POST /v1/sessions    ┌──────────────────────┐
│   Client    │ ───────────────────────▶│  FastAPI (mad.api)   │
│             │◀─── SSE stream ─────────│                      │
└─────────────┘                         └──────┬───────────────┘
                                               │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                      ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
                      │ Session Log  │ │   Sandbox    │ │   Harness    │
                      │ (the memory) │ │ (the hands)  │ │ (the brain)  │
                      └──────────────┘ └──────────────┘ └──────────────┘
```

## Components

### 1. Session Log — the memory

- One JSONL file per session at `./sessions/{session_id}.jsonl`.
- Append-only: each event is one JSON line.
- Public functions:
  - `create_session() -> session_id`
  - `emit(session_id, event_type, data)`
  - `get_events(session_id) -> list[event]`
- If the process crashes, a new instance reads the file and resumes from the last event. The log is the source of truth.

### 2. Sandbox — the hands

- One temporary directory per session at `/tmp/mad_{session_id}/`.
- Repositories are cloned here following their `mount_path` mapping (see `api.md`).
- Exposes a single interface: `execute(tool_name, input) -> string`.
- Tools available to the agent: `bash`, `read`, `write`, `edit`, `glob`, `grep`.
- GitHub tokens are used to clone and then stripped from the remote: `git remote set-url origin {url_without_token}`. Tokens never touch the workspace on disk.

### 3. Harness — the brain

The agent loop: call Claude → read structured response → execute tools → record events → repeat.

- **Stateless.** If it crashes, a new harness reads the session log and resumes.
- Supports two providers:
  - `claude_cli`: runs `claude --print --output-format stream-json` as a subprocess. For Pro/Max accounts.
  - `anthropic_api`: calls the Anthropic SDK directly. For pay-per-token usage.
- Runs in the background (asyncio task) after the first `user.message` is received. Does not block the HTTP endpoint.

## End-to-end request flow

```
1. POST /v1/sessions arrives with the JSON body
2. Schema is validated
3. session_id is generated and the session log is created
4. Temporary workspace directory is created
5. For each resource:
   - If type=github_repository: git clone with the token, to the mapped mount_path
   - If type=file: content is written to the mapped mount_path
6. Response: session_id + status "created" + resources_mounted
7. Client sends POST /events with a user.message to start the agent
8. Harness enters the agent loop:
   a. Build the prompt (system + workspace info + tool definitions + message)
   b. Call Claude (CLI or API) declaring the available tools
   c. Read the structured `tool_use` blocks Claude returns
   d. Execute each tool in the sandbox
   e. Record everything to the session log
   f. If there are more tool_use blocks, repeat from (a) feeding back `tool_result`
   g. When Claude stops or asks for human help, emit session.status_idle
9. SSE stream pushes each event to the client in real time
```

## Event vocabulary (session log)

Canonical event types emitted during a session:

- `session.created`
- `session.status_running`
- `session.status_idle` — includes `stop_reason`
- `user.message`
- `agent.message`
- `agent.tool_use` — includes `tool`, `input`
- `agent.tool_result` — includes `tool`, `result`
- `session.error`

The SSE stream is a 1:1 mirror of the session log: every event appended to the log is also pushed to any connected subscriber.
