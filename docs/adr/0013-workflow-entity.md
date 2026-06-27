# ADR-0013 — Workflow entity for sequential session chaining

- Status: Accepted
- Date: 2026-06-27
- Builds on: ADR-0009 (orchestration module), ADR-0011 (launcher working directory), and issues #88 (`task.git_result`) and #89 (host-sourced clone PAT)

## Context

ADR-0009 gave Mad a globally-serial dispatcher with per-session task queues, but
no way to express a dependency *between* sessions. Driving a multi-session
pipeline — "Session 1 refactors, Session 2 reviews the result" — forced an
external orchestrator to hold a process open on `GET /v1/events/stream`, wait for
`session.status_idle` from S1, read the branch it produced, and only then create
and start S2. That persistent waiter defeats the fire-and-forget model MCP
consumers expect (issue #90).

Two capabilities landed first and make a self-contained solution possible:

- **#88** records `task.git_result` (the branch/SHA a task produced, and whether
  it was pushed) — the fact a dependent session needs to check out its
  predecessor's output.
- **#89** sources the GitHub clone PAT from the host `GITHUB_TOKEN` / `GH_TOKEN`,
  so a dependent step can clone without a token travelling through any request.

## Decision

### 1. A `Workflow` is a DAG of steps; each step is one session + one task

The `Workflow` entity lives in `core/orchestration/` (the module ADR-0004 and
ADR-0009 anticipated for orchestration concerns). A step carries a session
configuration plus a task prompt and an optional `depends_on` list of predecessor
step ids. At run time a step is nothing more than a normal Mad session with a
single queued task: **"step completed" is exactly its `task.completed`**, and
"step failed" is its `task.failed` (including the orphan-recovery
`interrupted_by_restart` failure). This keeps the entire existing dispatch path
— ordering, policies, work windows, git-result capture — unchanged and reused;
workflow steps and standalone sessions are indistinguishable to the dispatcher.

### 2. A `WorkflowCoordinator` gates dependent steps; the dispatcher is untouched

A new bus-subscribing `WorkflowCoordinator` (sibling to the dispatcher) holds each
dependent step's task **unqueued** until **all** its `depends_on` predecessors
emit `task.completed`, then provisions that step's session and enqueues its task
through the same `CreateSessionUseCase` / `EnqueueTaskUseCase` the HTTP routes
call. The dispatcher's `_maybe_dispatch_next` eligibility logic is **not**
modified: gating lives entirely in the coordinator, so non-workflow sessions
behave exactly as before. With the v1 single-threaded dispatcher, independent
steps run one after another and a multi-dependency step waits for the last of its
predecessors — no parallelism required.

### 3. Branch propagation is a `from_step` mount, not an `inherit_branch` flag

A step's github mount is declared either explicitly (`url`) or as a reference to a
predecessor (`from_step` + `ref`). Modelling inheritance as a *mount source*
rather than a special flag composes: a step can mount repo A from one predecessor
and repo B from another, and can mix an inherited mount with a self-declared `url`
mount in the same list. `depends_on` and `from_step` are independent axes — a step
may declare `depends_on` with no `from_step` (a pure ordering barrier that clones
its own repo).

`from_step` mounts are materialized as a **fresh, independent clone** (never a
shared workspace) **just before** the dependent step's first task dispatches —
not at workflow-creation time. This resolves the provisioning-timing tension:
the predecessor's branch does not exist until it finishes, so a dependent session
cannot be fully provisioned up front.

### 4. The ref is resolved from `task.git_result`; `sha` is the default

`ref: "sha"` (default) pins the predecessor's immutable `head_sha` —
reproducible and immune to a TOCTOU race where the branch tip moves between S1
finishing and S2 cloning. `ref: "branch"` tracks the branch tip (opt-in). The ref
is read from the predecessor's recorded `task.git_result` **via the event log**,
not an in-memory cache: the dispatcher emits `task.completed` immediately before
`task.git_result`, so the coordinator reads the log (the source of truth, hard
rule 6) to stay race-free.

The fresh clone uses the host `GITHUB_TOKEN` / `GH_TOKEN` (#89), stripped from the
remote after clone (hard rule 2). Because a fresh clone pulls from origin, an
inherited ref that the predecessor did not push (`pushed == false`), or a detached
HEAD for `ref="branch"`, is **unresolvable** and fails the dependent step with a
clear reason — never a silent fall back to `main`.

### 5. Validation is at creation; state is JSONL-backed and replayed

`POST /v1/workflows` rejects a structurally invalid graph with 422 before
persisting: duplicate/empty step ids, an unknown `depends_on`, a dependency
cycle, a `from_step` not listed in its step's `depends_on`, and a `from_step`
pointing at a step with no github mount. The graph and per-step lifecycle are
recorded as `workflow.*` events under a reserved `workflow_id` stream, so a
workflow survives a process restart: `bootstrap_from_log` rebuilds the read
projection and the coordinator's state, and `resume` starts any step whose
predecessors completed while the process was down. In-flight step tasks recover
through the dispatcher's existing orphan mechanism.

### 6. Both routes are mirrored as MCP tools

`POST /v1/workflows` → `mad_create_workflow` and
`GET /v1/workflows/{workflow_id}` → `mad_get_workflow`, per hard rule 13
(ADR-0012). The parity test enforces it.

## Consequences

- An external orchestrator submits a whole pipeline in one fire-and-forget call
  and polls `GET /v1/workflows/{id}` for status — no SSE waiter, no glue process.
- The dispatcher stays single-purpose; all dependency logic is isolated in the
  coordinator, so the two can evolve independently.
- **Deferred (out of scope, future additive work):** parallel/concurrent dispatch
  of independent predecessors (the v1 dispatcher is globally serial; multi-
  dependency `depends_on` IS supported, only simultaneous execution is deferred),
  shared-workspace dependencies, cross-workflow dependencies, conditional
  branching, step-level retry/timeout policies beyond the session `timeout_s`, and
  passing structured output from one step to parameterise the next (content stays
  opaque, hard rule 1).
