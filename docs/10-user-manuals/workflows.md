---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Chain Sessions Into a Pipeline (Workflows)

## What this lets you do

A workflow runs several sessions in a fixed order automatically — a later
step waits for an earlier one to finish, and can pick up exactly what that
step produced (its branch or commit). Describe a whole pipeline ("refactor,
then review, then document") in one call instead of babysitting each stage
yourself.

## Before you start

- One or more agent configurations and prompts — a workflow creates its own
  sessions per step, you don't create them first.
- A rough shape in mind: which steps depend on which others.
- Which surface you're using — HTTP or MCP; both shown below.

## Step by step

### Step 1 — Describe the steps and create the workflow

Each step is its own session (an agent, a prompt, mounts) plus an optional
`depends_on` list of earlier step ids. A step only starts once every step in
its `depends_on` has completed.

#### Using the HTTP API

```bash
curl -sS -X POST http://localhost:8000/v1/workflows \
  -H 'Content-Type: application/json' \
  -d '{
        "steps": [
          {
            "id": "refactor",
            "session": {
              "agent": {"name": "refactor-bot", "provider": "claude_cli"},
              "prompt": "Refactor the payments module for clarity.",
              "mounts": [
                {"mount_path": "/workspace/repo", "type": "github_repository", "url": "https://github.com/your-org/your-repo.git"}
              ]
            }
          },
          {
            "id": "review",
            "depends_on": ["refactor"],
            "session": {
              "agent": {"name": "review-bot", "provider": "claude_cli"},
              "prompt": "Review the changes from the refactor step.",
              "mounts": [
                {"mount_path": "/workspace/repo", "type": "github_repository", "from_step": "refactor", "ref": "branch"}
              ]
            }
          }
        ]
      }'
```

#### Using MCP tools

```
mad_create_workflow({
  "payload": {
    "steps": [
      {
        "id": "refactor",
        "session": {
          "agent": {"name": "refactor-bot", "provider": "claude_cli"},
          "prompt": "Refactor the payments module for clarity.",
          "mounts": [
            {"mount_path": "/workspace/repo", "type": "github_repository", "url": "https://github.com/your-org/your-repo.git"}
          ]
        }
      },
      {
        "id": "review",
        "depends_on": ["refactor"],
        "session": {
          "agent": {"name": "review-bot", "provider": "claude_cli"},
          "prompt": "Review the changes from the refactor step.",
          "mounts": [
            {"mount_path": "/workspace/repo", "type": "github_repository", "from_step": "refactor", "ref": "branch"}
          ]
        }
      }
    ]
  }
})
```

The `review` step's mount uses `from_step` instead of its own `url` — it
inherits the `refactor` step's repo and checks out what that step produced.
`ref: "branch"` tracks the branch tip; `ref: "sha"` (the default) pins the
exact commit instead.

Response:

```json
{"workflow_id": "wkfl_9c2a1b7e4f6a", "status": "pending"}
```

### Step 2 — Check on it

#### Using the HTTP API

```bash
curl -sS http://localhost:8000/v1/workflows/wkfl_9c2a1b7e4f6a
```

#### Using MCP tools

```
mad_get_workflow({"workflow_id": "wkfl_9c2a1b7e4f6a"})
```

Response (trimmed):

```json
{
  "workflow_id": "wkfl_9c2a1b7e4f6a",
  "status": "running",
  "steps": [
    {"step_id": "refactor", "status": "completed", "depends_on": [], "session_id": "sesn_3f9a8b2c1d4e"},
    {"step_id": "review", "status": "running", "depends_on": ["refactor"], "session_id": "sesn_a1b2c3d4e5f6"}
  ]
}
```

The workflow's own `status` rolls up all its steps: `pending` → `running` →
`completed`, or `failed` the moment any step fails.

## What you get back

The `workflow_id` for polling, and each step's own `status` / `session_id` —
a step is a normal session under the hood, so [`sessions.md`](sessions.md)
and [`events.md`](events.md) both apply to it once it's running.

## Under the hood

A workflow is an assembly line: each station (step) waits for the part from
the station before it to arrive before starting its own work, and a station
can be handed exactly what the previous one built (`from_step`) instead of
starting from scratch. Mad runs the line and moves parts between stations —
it never does any of the assembly itself; that's still the agent's job at
each station.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `422` creating the workflow | A cyclic `depends_on`, an unknown step id referenced, or a `from_step` pointing at a step with no repo mount | Check every `depends_on` / `from_step` id exists and the graph has no cycle |
| A step never starts | Its `depends_on` predecessors haven't all completed yet | Check the workflow's per-step `status` — it's waiting, not stuck |
| Workflow `status` is `failed` | One step failed (or was interrupted by a restart) and downstream steps were never started | Read that step's `session_id` events (see [`events.md`](events.md)) for the failure reason |
| A downstream step checked out the wrong code | `ref` defaulted to `"sha"` (pinned) when you expected `"branch"` (moving), or vice-versa | Set `ref` explicitly on the `from_step` mount |

## See also

- [`sessions.md`](sessions.md) — each workflow step is one of these under
  the hood.
- [`queue-and-scheduling.md`](queue-and-scheduling.md) — how an individual
  step's task is handled once it's eligible to run.
