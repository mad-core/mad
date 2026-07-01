---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Choose Your Agent, Model, and Reasoning Effort

## What this lets you do

Pick which coding agent runs your work, which of that agent's models handles
it, and how hard it should think before answering. Set a deployment-wide
default once, or override it for a single session or a single task.

## Before you start

- Know your options: today `claude_cli` and `opencode` are the available
  agents, chosen per session via `agent.provider` (see
  [`sessions.md`](sessions.md)).
- Effort is a free-form string Mad passes straight through to the agent
  (`--effort` for Claude, `--variant` for OpenCode) — Mad doesn't validate
  it, so use whatever level your agent's own docs describe.
- Overrides stack in one direction: a task-level choice beats a
  session-level choice, which beats the deployment default.

## Step by step

### Step 1 — See what models are available

#### Using the HTTP API

```bash
curl -sS http://localhost:8000/v1/providers/models
```

#### Using MCP tools

```
mad_list_provider_models({})
```

Response:

```json
{
  "providers": {
    "claude_cli": ["opus", "sonnet", "haiku"],
    "opencode": ["anthropic/claude-sonnet-4-5", "anthropic/claude-opus-4", "openai/gpt-4o"]
  }
}
```

### Step 2 — Set (or clear) the deployment-wide default model

Every session that doesn't specify its own model uses this one.

#### Using the HTTP API

```bash
curl -sS -X PUT http://localhost:8000/v1/model \
  -H 'Content-Type: application/json' -d '{"model": "sonnet"}'
```

#### Using MCP tools

```
mad_set_deployment_model({"payload": {"model": "sonnet"}})
```

Read it back, or drop it back to "no opinion" (the agent's own default):

```bash
curl -sS http://localhost:8000/v1/model
curl -sS -X DELETE http://localhost:8000/v1/model
```

```
mad_get_deployment_model({})
mad_clear_deployment_model({})
```

### Step 3 — Same, for reasoning effort

#### Using the HTTP API

```bash
curl -sS -X PUT http://localhost:8000/v1/effort \
  -H 'Content-Type: application/json' -d '{"effort": "high"}'
```

#### Using MCP tools

```
mad_set_deployment_effort({"payload": {"effort": "high"}})
```

`GET`/`DELETE /v1/effort` (`mad_get_deployment_effort` /
`mad_clear_deployment_effort`) read or clear it the same way.

### Step 4 — Override per session, or per task

A session can pin its own model/effort at creation time, overriding the
deployment default just for it:

```bash
curl -sS -X POST http://localhost:8000/v1/sessions \
  -H 'Content-Type: application/json' \
  -d '{"agent": {"name": "my-agent", "provider": "claude_cli"}, "model": "opus", "effort": "high"}'
```

And a single queued task can override the model just for that one run
(there is no task-level effort override — effort stops at the session
level):

```bash
curl -sS -X POST http://localhost:8000/v1/sessions/sesn_3f9a8b2c1d4e/tasks \
  -H 'Content-Type: application/json' \
  -d '{"content": "Do a quick pass, use the cheaper model.", "model": "haiku"}'
```

Both are the same fields on `mad_create_session` / `mad_enqueue_task`.

## What you get back

`GET /v1/model` and `GET /v1/effort` both return `null` when nothing is
set — that's not an error, it means "let the agent use its own default."
The precedence to remember: **task model** > **session model/effort** >
**deployment default** > **agent's own default**.

## Under the hood

Think of it like ordering at a restaurant with several kitchens: the
provider is which kitchen takes your order, the model is which chef in that
kitchen cooks it, and effort is how carefully you've asked them to think it
through. Mad is the front desk that takes your order and routes it to the
right kitchen — it never cooks anything itself.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `422` creating a session or task with a `model` | The model isn't in that provider's catalog | Call `mad_list_provider_models` / `GET /v1/providers/models` first and use one of the listed ids |
| Setting `effort` seems to do nothing | The value isn't one your agent's CLI recognizes — Mad forwards it verbatim without checking | Check your agent's own docs for valid effort/variant levels |
| A session isn't using the model you just set as the deployment default | The session (or its task) already has its own override, which always wins | Clear the session/task-level override, or set it explicitly to match |
| `mad_list_provider_models` returns fewer models than expected for `opencode` | Live discovery via the CLI failed, or the CLI isn't installed, so Mad fell back to a short static list | Confirm the `opencode` CLI is installed and on `PATH` where Mad runs |

## See also

- [`sessions.md`](sessions.md) — where the session-level `model`/`effort`
  fields are set.
- [`queue-and-scheduling.md`](queue-and-scheduling.md) — where the
  task-level `model` field is set.
