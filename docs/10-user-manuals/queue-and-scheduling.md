---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Queue Prompts and Control When They Run

## What this lets you do

Instead of sending one prompt and waiting, you can line up several tasks on
a session and let Mad work through them in order — and decide whether they
run the instant they're queued, only during hours you set, or only when you
explicitly say go.

## Before you start

- An existing session (see [`sessions.md`](sessions.md)) — tasks queue onto
  a session, they don't create one.
- Which surface you're using — HTTP or MCP; both are shown below.
- Your starting point: every session inherits one deployment-wide default
  for when its queue runs, until you override it.

## Step by step

### Step 1 — Queue a task

#### Using the HTTP API

```bash
curl -sS -X POST http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/tasks \
  -H 'Content-Type: application/json' \
  -d '{"content": "Run the test suite and report failures."}'
```

#### Using MCP tools

```
mad_enqueue_task({
  "session_id": "sesn_3f9a8b2c1d4e",
  "payload": {"content": "Run the test suite and report failures."}
})
```

Response:

```json
{"task_id": "8f14e45f-9c2a-4b1e-9d3a-6f2c8e1a4b7d", "session_id": "sesn_3f9a8b2c1d4e", "scheduled_for": "now", "status": "queued"}
```

### Step 2 — See what's queued on a session

#### Using the HTTP API

```bash
curl -sS http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/tasks
```

#### Using MCP tools

```
mad_list_tasks({"session_id": "sesn_3f9a8b2c1d4e"})
```

Response (trimmed):

```json
{
  "queued": [
    {"task_id": "8f14e45f-9c2a-4b1e-9d3a-6f2c8e1a4b7d", "content": "Run the test suite and report failures.", "scheduled_for": "now"}
  ],
  "in_flight": null
}
```

### Step 3 — Cancel a queued task

Only tasks still waiting can be cancelled — one already running has to
finish.

#### Using the HTTP API

```bash
curl -sS -X DELETE http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/tasks/8f14e45f-9c2a-4b1e-9d3a-6f2c8e1a4b7d
```

#### Using MCP tools

```
mad_cancel_task({"session_id": "sesn_3f9a8b2c1d4e", "task_id": "8f14e45f-9c2a-4b1e-9d3a-6f2c8e1a4b7d"})
```

### Step 4 — See the whole line, across every session

#### Using the HTTP API

```bash
curl -sS http://localhost:8000/v1/queue
```

#### Using MCP tools

```
mad_get_queue({})
```

Response (trimmed):

```json
{
  "in_flight": {"task_id": "…", "session_id": "sesn_3f9a8b2c1d4e", "priority": 1},
  "ready": [
    {"task_id": "…", "session_id": "sesn_a1b2c3d4e5f6", "priority": 3}
  ],
  "scheduled": [
    {"task_id": "…", "session_id": "sesn_b2c3d4e5f6a1", "reason": {"kind": "window", "scheduled_for": "2026-07-01T18:00:00Z"}}
  ]
}
```

`ready[0]` is exactly what runs next. `scheduled` holds anything gated by a
work window or manual mode, with the `reason` it's waiting.

### Step 5 — Control WHEN a session's queue runs

Three policies: `immediate` (default — run as soon as it's next in line),
`work_window` (only inside hours you set), `manual` (only when you say go).

#### Using the HTTP API

```bash
curl -sS -X PATCH http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/dispatch_policy \
  -H 'Content-Type: application/json' \
  -d '{"kind": "work_window", "windows": [{"start": "18:00", "end": "08:00", "timezone": "America/Mexico_City"}]}'
```

#### Using MCP tools

```
mad_set_session_dispatch_policy({
  "session_id": "sesn_3f9a8b2c1d4e",
  "payload": {"kind": "work_window", "windows": [{"start": "18:00", "end": "08:00", "timezone": "America/Mexico_City"}]}
})
```

Drop the override and fall back to the deployment default with
`mad_clear_session_dispatch_policy` (`DELETE .../dispatch_policy`). Read or
set that deployment-wide default itself with `GET`/`PUT /v1/dispatch_policy`
(`mad_get_deployment_dispatch_policy` / `mad_set_deployment_dispatch_policy`).

In `manual` mode, nothing runs until you trigger a drain:

```bash
curl -sS -X POST http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/dispatch_policy/trigger
```

```
mad_trigger_dispatch({"session_id": "sesn_3f9a8b2c1d4e"})
```

### Step 6 — Prioritize a session over others

Higher numbers go first when several sessions have work waiting (1–10,
default 1):

#### Using the HTTP API

```bash
curl -sS -X PATCH http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/priority \
  -H 'Content-Type: application/json' -d '{"priority": 8}'
```

#### Using MCP tools

```
mad_set_session_priority({"session_id": "sesn_3f9a8b2c1d4e", "payload": {"priority": 8}})
```

## What you get back

The fields that matter across these calls: `task_id` (to cancel later),
`scheduled_for` (the hint you gave, recorded verbatim), and on the queue
view, `ready[0]` — the one true "what runs next" answer, computed the same
way Mad itself decides.

## Under the hood

Picture a ticket line at a counter with posted opening hours: everyone takes
a ticket (a queued task), the counter serves one ticket at a time in order,
and a `work_window` policy is just the counter's posted hours — no tickets
get called outside them, even though the line keeps growing. `manual` mode
is a counter that stays shut until someone flips the sign to open. Mad runs
the counter; it never fills in for the person being called up.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| A queued task never seems to start | The session's effective policy is `work_window` (outside hours) or `manual` (no trigger yet) | Check `GET /v1/queue` — a `scheduled` entry shows the `reason`; wait for the window, or call the trigger |
| `409` triggering a manual drain | The session's effective policy isn't `manual` | Set it to `manual` first with `dispatch_policy`, then trigger |
| `409` cancelling a task | The task already started running — it can't be cancelled mid-flight | Let it finish, or delete the session if you need to stop it hard |
| A high-priority session still isn't dispatching first | Priority only breaks ties across *ready* sessions — a `work_window`/`manual` gate is checked first | Check the session's own dispatch policy, not just its priority |

## See also

- [`sessions.md`](sessions.md) — sessions are what tasks queue onto.
- [`workflows.md`](workflows.md) — chaining tasks across sessions instead of
  within one.
