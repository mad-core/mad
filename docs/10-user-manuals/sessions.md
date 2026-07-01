---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Run an Agent on Your Repo (Sessions)

## What this lets you do

A session is where one agent does one job against one workspace: you create
it once, send it prompts, and watch it move from created to running to idle
(or error). This page covers the whole lifecycle — create, message, inspect,
list, and clean up.

## Before you start

- Mad's URL (for example `http://localhost:8000`, or your tunnel hostname).
- The repo URL you want the agent to work on. If it's private, its clone
  token lives on the **host** running Mad (`GITHUB_TOKEN` / `GH_TOKEN`) —
  never inside a request.
- Which surface you're using: plain HTTP, or an MCP client. Both do the same
  thing; every step below shows both.

## Step by step

### Step 1 — Create a session

Creating a session provisions its own workspace, mounts whatever resources
you list (a cloned repo, a written file), and gives you back a `session_id`
you reuse for every step after this one.

#### Using the HTTP API

```bash
curl -sS -X POST http://localhost:8000/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{
        "agent": {"name": "refactor-bot", "provider": "claude_cli"},
        "resources": [
          {
            "type": "github_repository",
            "url": "https://github.com/your-org/your-repo.git",
            "mount_path": "/workspace/repo"
          }
        ],
        "base_branch": "main"
      }'
```

#### Using MCP tools

```
mad_create_session({
  "payload": {
    "agent": {"name": "refactor-bot", "provider": "claude_cli"},
    "resources": [
      {
        "type": "github_repository",
        "url": "https://github.com/your-org/your-repo.git",
        "mount_path": "/workspace/repo"
      }
    ],
    "base_branch": "main"
  }
})
```

Response (trimmed):

```json
{
  "session_id": "sesn_3f9a8b2c1d4e",
  "status": "created",
  "workspace": "/home/you/mad/mad_sesn_3f9a8b2c1d4e",
  "resources_mounted": [
    {"type": "github_repository", "mount_path": "/workspace/repo", "status": "cloned"}
  ]
}
```

Keep the `session_id` — every following step needs it.

### Step 2 — Send it a message

Sending a message hands the agent a prompt and returns immediately — it does
not wait for the agent to finish. Only one prompt can be in flight per
session at a time.

#### Using the HTTP API

```bash
curl -sS -X POST http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/messages \
  -H 'Content-Type: application/json' \
  -d '{"content": "Add type hints to the payments module and open a PR."}'
```

#### Using MCP tools

```
mad_send_message({
  "session_id": "sesn_3f9a8b2c1d4e",
  "payload": {"content": "Add type hints to the payments module and open a PR."}
})
```

Response:

```json
{"status": "accepted"}
```

The agent is now working — move to Step 3 to watch it.

### Step 3 — Check on it

#### Using the HTTP API

```bash
curl -sS http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e
```

#### Using MCP tools

```
mad_get_session({"session_id": "sesn_3f9a8b2c1d4e"})
```

Response (trimmed):

```json
{
  "session_id": "sesn_3f9a8b2c1d4e",
  "status": "running",
  "workspace": "/home/you/mad/mad_sesn_3f9a8b2c1d4e",
  "events": [
    {"type": "session.created"},
    {"type": "user.message"},
    {"type": "session.status_running"},
    "…more as the agent works…"
  ],
  "last_conversation_id": null
}
```

`status` plus the tail of `events` tells you where things stand — see
[`events.md`](events.md) for the live stream and the full vocabulary.

### Step 4 — List and filter your sessions

#### Using the HTTP API

```bash
curl -sS "http://localhost:8000/v1/sessions?order_by=updated_at&order=desc"
```

#### Using MCP tools

```
mad_list_sessions({"order_by": "updated_at", "order": "desc"})
```

Response (trimmed, one entry):

```json
[
  {"session_id": "sesn_3f9a8b2c1d4e", "status": "idle", "priority": 1, "created_at": "2026-07-01T12:00:00Z", "updated_at": "2026-07-01T12:00:41Z"}
]
```

Other filters: `created_after` / `created_before` / `updated_after` /
`updated_before`, and `include_deleted` if you want deleted sessions listed
too.

### Step 5 — Delete it, or clean up in bulk

A single delete cancels any queued work, tears down the workspace, and marks
the session deleted.

#### Using the HTTP API

```bash
curl -sS -X DELETE http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e
```

#### Using MCP tools

```
mad_delete_session({"session_id": "sesn_3f9a8b2c1d4e"})
```

For bulk cleanup, set a cutoff and preview it first with `dry_run`:

#### Using the HTTP API

```bash
curl -sS -X POST http://localhost:8000/v1/sessions/cleanup \
  -H 'Content-Type: application/json' \
  -d '{"older_than": "2026-06-01T00:00:00Z", "dry_run": true}'
```

#### Using MCP tools

```
mad_cleanup_sessions({"payload": {"older_than": "2026-06-01T00:00:00Z", "dry_run": true}})
```

Response:

```json
{"deleted_session_ids": [], "would_delete": ["sesn_a1b2c3d4e5f6", "sesn_b2c3d4e5f6a1"], "examined": 14}
```

Once `would_delete` looks right, drop `dry_run` (or set it `false`) and those
sessions are actually torn down.

## What you get back

The field to watch across all of the above is `status` — it is the single
source of truth for where a session stands.

### The life of a session

```
created ──▶ running ──▶ idle
                   └──▶ error
```

- **created** — the workspace exists and resources are mounted; no prompt
  sent yet.
- **running** — a prompt is in flight; the agent is working.
- **idle** — the agent finished cleanly (exit 0). Send another message any
  time.
- **error** — the agent exited with a failure, hit its time budget, or
  something else went wrong; read the events for detail.

Any of these can move to **deleted** — the end of the line.

## Under the hood

The session is a hotel room Mad rents for your project: Mad prepares a
clean private room with a fresh copy of your repo, and sending a message is
like phoning the specialist working in that room and asking them to do
something. If your repo is private, Mad borrows your house key once at
check-in to fetch it, then throws the key away — it never keeps a copy.
Checking out clears the room for good. Mad is the hotel, not the specialist:
it never does the work itself, it just gives the specialist somewhere safe
to work and tells you what happened.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `409` sending a message | A previous prompt on this session is still running — one in flight per session | Wait for it to finish, or queue the next prompt instead — see [`queue-and-scheduling.md`](queue-and-scheduling.md) |
| A private repo didn't clone | No GitHub token on the machine running Mad | Set `GITHUB_TOKEN` (or `GH_TOKEN`) on that host, then create the session again |
| `400` "invalid mount_path" on create | A `mount_path` tried to point outside the session's workspace | Use a path under `/workspace/...` — anything that would escape it is rejected |
| Session `status` is `error` | The agent exited with a failure or ran past its time budget | Read the session's events (or [`events.md`](events.md)) for the failure detail, then send a new message to retry |

## See also

- [`events.md`](events.md) — read the full history, or watch it live.
- [`queue-and-scheduling.md`](queue-and-scheduling.md) — line up more than
  one prompt per session.
- [`choosing-agent-and-model.md`](choosing-agent-and-model.md) — pick the
  agent/model/effort a session uses.
