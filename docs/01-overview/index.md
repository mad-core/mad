---
service: mad
domain: backend
section: Overview
source_of_truth: repo
---

# Overview

Mad — **M**ulti **A**gent **D**evelop — is a self-hosted infrastructure layer.
It provisions an isolated workspace, clones a GitHub repository into it, launches
an external autonomous coding agent (Claude Code, OpenCode, …) against that
workspace, and streams the agent's stdout back to the caller as events. It is the
substrate that runs agents; it is **not** the agent. This page is the intent-level
orientation for a new engineer: what Mad is, the boundary it owns, who it talks
to, and — just as important — what it deliberately refuses to do.

The authoritative scope contract lives in [`CLAUDE.md`](../../CLAUDE.md) (the
"What this project is" section plus the numbered hard rules) and the
[`README.md`](../../README.md). Where this page summarizes, those documents and
the [ADRs](../adr/) govern.

## What Mad is

- A **back-end service**, distributed on PyPI as the `mad-bros` package, imported
  as `mad`, and started with the `mad serve` console script (`pyproject.toml`,
  `src/mad/entry_points/cli.py`). It is **self-hosted**: an operator runs it on a
  Linux host they control.
- **Infrastructure, not an orchestrator.** Mad spawns an external agent process,
  streams its stdout line-by-line as `agent.output` events, and reports when the
  process finishes. The agent's own harness owns the reasoning loop, tool
  execution, and LLM calls — Mad never looks inside (`CLAUDE.md` hard rule 1).
- **Early-stage.** The package is still `0.x` (alpha). Multi-tenancy is
  deliberately deferred ([ADR-0006](../adr/0006-multi-tenancy-deferred.md)), and
  the "multi-agent team that ships an idea end-to-end" framing is a future vision
  built *on top of* this substrate, not what ships today
  ([`README.md`](../../README.md), "Vision").

## Why it exists — the problem it solves

Running a coding agent against a real repository safely and repeatably is a pile
of undifferentiated plumbing: create an isolated working directory, clone the
right repo at the right ref without leaking the access token, spawn the agent CLI
with the correct working directory and environment, capture its output as a
durable stream a client can follow live or replay later, and know when it
finished and whether it succeeded. Mad does exactly that plumbing once, behind a
typed HTTP / MCP / CLI surface, so any consumer (a human, or — more commonly — an
AI agent) can launch agent runs without reimplementing workspace isolation,
token hygiene, or output streaming.

Crucially, Mad stays out of the agent's way. Different agents (Claude Code,
OpenCode, Codex, …) bring incompatible harnesses; by treating the agent as an
opaque subprocess whose stdout is a stream, Mad supports any of them without
coupling to one vendor's loop or response format.

## What Mad is responsible for — the bounded context it owns

Mad's `mad.core` is framework-free and organized into three bounded contexts
(`CLAUDE.md` hard rule 4; [ADR-0003](../adr/0003-package-layout.md)):

- **Sessions** — the core lifecycle. A *session* is one isolated workspace plus
  the agent runs executed in it. Mad owns: provisioning the workspace under a
  base directory (`~/mad` by default, override `MAD_WORKSPACE_DIR`), mounting
  *resources* into it (`github_repository` clones and literal `file` content) at
  a validated `mount_path`, launching the external agent with the right working
  directory ([ADR-0011](../adr/0011-launcher-working-directory.md)), and emitting
  `session.status_idle` (agent exited 0) or `session.error` (non-zero / timeout)
  on completion.
- **Events** — observability only. A single cross-session JSONL log is the
  **source of truth** (`CLAUDE.md` hard rule 6): every action is appended there
  and also streamed. Mad exposes this vocabulary *verbatim* over SSE and a
  historical query API; it never translates, classifies, or acts on events
  ([ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md)). The single
  write path is `EventEmitter.emit()` (hard rule 11,
  [ADR-0007](../adr/0007-single-write-gateway-event-emitter.md)).
- **Orchestration** — control-plane scheduling of *when* a session runs queued
  work, not what the agent does. It owns a per-session task queue, dispatch
  policies (e.g. immediate, manual-trigger, time-window), priority ordering,
  retries, and deployment-wide model / effort defaults. Tasks are **opaque
  blobs** — orchestration decides *when* to launch, never parses task content
  ([ADR-0009](../adr/0009-orchestration-module.md)).

Two security invariants run through all of this: **token hygiene** — a GitHub
token is used once for `git clone`, then stripped from the remote and never
persisted to the workspace, log, or stdout (hard rule 2) — and **path-traversal
prevention** — `mount_path` values are confined to the workspace; escaping
absolute paths are rejected before any filesystem operation (hard rule 3).

## What Mad explicitly does NOT do

- **Does not manage an agent loop, execute tools, or parse LLM responses.** The
  external agent's harness owns all of that (hard rule 1). Mad sees stdout, not
  tool calls.
- **Does not inspect task content.** Prompts and queued tasks are opaque; Mad
  routes and schedules them, it does not read or rewrite them (ADR-0009).
- **Does not act on events.** The events module is a verbatim observability
  surface — no webhooks, schedulers, or dispatch live there (hard rule 8 /
  ADR-0004). (Control-plane reactions live in orchestration instead.)
- **Does not coordinate multiple sessions into one autonomous "team."** Sessions
  run in parallel, each with its own process and event stream; cross-session
  goal coordination is future work, not today's scope
  ([`README.md`](../../README.md), "Vision").
- **Is not multi-tenant.** There is no per-tenant isolation or auth model in the
  app today (ADR-0006); authentication is expected at the edge (e.g. a
  Cloudflare Access tunnel), not inside Mad.
- **Does not persist secrets or its own side-state.** No database; the JSONL
  event log is the only durable state, and tokens never reach it (hard rules 2, 6).

## Systems it talks to

### Upstream — who drives Mad

A **consumer** initiates everything. In practice the consumer is most often an AI
agent speaking MCP, but it can equally be a human with `curl` or a script. Mad
exposes the same capabilities over several parallel surfaces (see below); none of
them is privileged over the others.

### Downstream — what Mad depends on to do its job

- **GitHub** — repositories are cloned over HTTPS using the per-request
  `authorization_token`, which is then stripped from the remote (hard rule 2). No
  GitHub App, webhooks, or persistent credentials.
- **External agent CLIs** — Mad spawns the agent as a subprocess with its working
  directory set to the cloned repo. Production launchers today are `claude_cli`
  (the `claude` binary, override `MAD_CLAUDE_CLI_BIN`) and `opencode` (override
  `MAD_OPENCODE_BIN`), dispatched by name via `factory.get_launcher`; the design
  target is any external coding-agent CLI.
- **The local filesystem** — the isolated workspace tree (`~/mad` /
  `MAD_WORKSPACE_DIR`) and the session event log (`./sessions` /
  `MAD_SESSIONS_DIR`, the source of truth).
- **Agent hook callbacks (loop-back)** — the spawned `claude` agent posts
  lifecycle hooks back to a Mad-internal adapter over a Unix domain socket; those
  arrive as `agent.<provider>.hook.*` events on the same stream
  ([ADR-0008](../adr/0008-internal-hook-adapter-and-vocabulary.md)). This is the
  one path where a downstream agent calls *back* into Mad.

## How you interact with it — the surfaces

`mad serve` starts two uvicorn servers: the public app, and an internal
UDS-bound app that only receives agent hook callbacks
(`src/mad/entry_points/cli.py`). The public app
(`src/mad/adapters/inbound/http/app.py`) wires these consumer-facing surfaces:

| Surface | Endpoint / entry | Purpose |
|---|---|---|
| HTTP — sessions | `/v1/sessions*` | Create a session, send a message (launches the agent), get / list / delete / clean up sessions. |
| HTTP — orchestration | `/v1/sessions/{id}/tasks*`, `/v1/queue`, dispatch-policy routes | Queue tasks, inspect the global queue, set per-session and deployment dispatch policy, trigger a manual dispatch. |
| HTTP — providers | `/v1/providers/models`, `/v1/model`, `/v1/effort` | List available provider models; read / set / clear deployment-wide model and effort defaults. |
| SSE — events | `GET /v1/events/stream` | Live, resumable (`Last-Event-ID`, [ADR-0005](../adr/0005-uuidv7-event-id.md)) event stream; `GET /v1/events` replays history. |
| MCP | mounted at `/mcp` | The same use cases as the HTTP routes, exposed as in-process tools — in practice the most-used surface ([ADR-0010](../adr/0010-mcp-mounted-http-inbound-adapter.md)). |
| CLI | `mad serve [--host --port]` | The console script that boots the servers. |

HTTP and MCP are kept at strict parity: every request/response `/v1` route has
exactly one mirroring MCP tool calling the same use case (hard rule 13,
[ADR-0012](../adr/0012-http-mcp-tool-parity.md)); the only carve-out is the SSE
stream, which is telemetry rather than a request/response tool. All HTTP bodies
and responses are strongly typed Pydantic models, which is what populates
OpenAPI / `/docs` (hard rule 9).

A minimal flow: `POST /v1/sessions` provisions the workspace and clones the repo,
then `POST /v1/sessions/{id}/messages` sends the first prompt (this is what
launches the agent), and `GET /v1/events/stream` follows the run. See the
[`README.md`](../../README.md) Quickstart for runnable `curl` examples.

## Where to go next

- [Architecture source tree](../02-architecture/source-tree.md) — the hexagonal
  ports-and-adapters layout in code form (rationale in
  [ADR-0003](../adr/0003-package-layout.md)).
- [API reference](../03-api/api-reference.md) — the full HTTP surface from the
  OpenAPI spec.
- [`CLAUDE.md`](../../CLAUDE.md) — the binding hard rules every change must honor.
- [ADR index](../adr/) — the *why* behind each structural decision.
</content>
</invoke>
