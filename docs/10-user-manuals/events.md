---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Watch What Your Agents Do (Events)

## What this lets you do

Every action Mad takes — a session being created, a line of agent output, a
task finishing — is recorded as an update. This page shows you how to read
that history after the fact, and how to watch it live as it happens.

## Before you start

- A session id, if you want to filter to just one session (leave it off to
  see everything).
- A sense of which you need: history (a bounded query, good for polling
  from anywhere) or a live tail (a long-lived connection, good for watching
  in real time).
- The live tail is HTTP-only. There is no MCP tool for it — see Step 2.

## Step by step

### Step 1 — Query the history

#### Using the HTTP API

```bash
curl -sS "http://localhost:8000/v1/events?session_id=sesn_3f9a8b2c1d4e&limit=50"
```

#### Using MCP tools

```
mad_query_events({"session_id": "sesn_3f9a8b2c1d4e", "limit": 50})
```

Response (trimmed):

```json
{
  "events": [
    {"event_id": "0195e2b1-0000-7000-8000-000000000001", "session_id": "sesn_3f9a8b2c1d4e", "type": "agent.output", "data": {"line": "Reading README.md..."}, "timestamp": "2026-07-01T12:00:03Z"},
    {"event_id": "0195e2b1-0000-7000-8000-000000000002", "session_id": "sesn_3f9a8b2c1d4e", "type": "session.status_idle", "data": {}, "timestamp": "2026-07-01T12:00:41Z"}
  ],
  "next_cursor": null
}
```

More filters: `kind` (event type), `agent`, `since` (an ISO timestamp). When
`next_cursor` is non-null, pass it back as `after_event_id` to fetch the next
page.

### Step 2 — Watch it live

This is HTTP-only — there is no matching MCP tool for a live tail. If you're
driving Mad through an MCP client, either open this endpoint directly with
any HTTP/SSE-capable tool, or fall back to repeating Step 1
(`mad_query_events` with `after_event_id`) every few seconds.

#### Using the HTTP API

```bash
curl -N "http://localhost:8000/v1/events/stream?session_id=sesn_3f9a8b2c1d4e"
```

Each frame that arrives looks like:

```
id: 0195e2b1-0000-7000-8000-000000000003
data: {"event_id": "0195e2b1-0000-7000-8000-000000000003", "session_id": "sesn_3f9a8b2c1d4e", "type": "agent.output", "data": {"line": "Running tests..."}, "timestamp": "2026-07-01T12:00:12Z"}
```

Same filters as history: `session_id`, `kind`, `agent`.

### Step 3 — Resume where you left off

If your connection drops, reconnect with a `Last-Event-ID` header set to the
last `event_id` you saw. Mad replays everything you missed from the log,
then hands off to the live feed with no gap and no duplicates.

```bash
curl -N -H "Last-Event-ID: 0195e2b1-0000-7000-8000-000000000003" \
  "http://localhost:8000/v1/events/stream?session_id=sesn_3f9a8b2c1d4e"
```

## What you get back

Every event, live or historical, has the same shape: `event_id` (sortable —
use it to resume), `session_id`, `type`, `data`, `timestamp`. The types worth
knowing as a user:

| Type | What it means |
|---|---|
| `agent.output` | One line the agent printed while working. |
| `session.status_idle` | The agent finished cleanly — your "it's done" signal. |
| `session.error` | The agent failed or ran past its time budget. |
| `agent.<provider>.hook.*` | A detailed, lower-level trace of what the agent's own tooling did internally (individual tool calls, file edits). Useful when you need to dig deeper than the plain output line; safe to ignore otherwise. |

## Under the hood

Think of the event log as a security camera pointed at the room Mad rented
you, feeding both a live monitor and a written logbook. You can watch the
monitor as things happen, or open the logbook later and start reading from
any page you already got to. Mad only reports what it observes — it never
decides whether an event is good or bad news; that judgment is yours.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| The stream connects but nothing arrives | No matching events yet, or your filters are too narrow | Drop the `kind`/`agent` filter temporarily, or send the session a message to generate activity |
| Stream drops after a while through a proxy or tunnel | An idle connection was cut by something in between | Reconnect with `Last-Event-ID` set to your last-seen `event_id` — nothing is lost |
| `mad_query_events` looks incomplete | You're on the last page | Check whether `next_cursor` is non-null and pass it as `after_event_id` |
| Occasional blank/keepalive lines on the stream | Normal — a heartbeat Mad sends when nothing has happened for a while | Ignore it; your SSE client already does |

## See also

- [`sessions.md`](sessions.md) — the operations that generate these events.
- [`queue-and-scheduling.md`](queue-and-scheduling.md) — the task-lifecycle
  events (`task.queued`, `task.completed`, …).
