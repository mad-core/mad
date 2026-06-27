---
service: mad
domain: backend
section: Architecture
source_of_truth: repo
---

# Architecture

## Architectural style

Mad is a **hexagonal (ports-and-adapters) application**. The codebase under `src/mad/`
splits into exactly two halves:

- `mad.core` — the **business core** (the interior of the hexagon). It holds bounded
  contexts, their domain entities, their application use cases, and the *port*
  interfaces those use cases depend on. It is framework-free and adapter-free: no
  FastAPI, no `subprocess`, no `mad.adapters` imports. This is CLAUDE.md hard rule 4,
  recorded structurally in [ADR-0003](../adr/0003-package-layout.md) and enforced
  mechanically by `import-linter`.
- `mad.adapters` — the **I/O edge** (the exterior). *Inbound* adapters (HTTP routes,
  MCP tools, the internal hook receiver) drive the use cases; *outbound* adapters
  (JSONL persistence, workspace provisioner, agent launchers, the event bus/log,
  the task projection) implement the ports the use cases call.

Inside `mad.core`, code is organized **domain-first** rather than by technical layer:
each bounded context (`sessions/`, `events/`, `orchestration/`) owns its own
`domain/`, `ports/`, and `use_cases/` subtree, instead of grouping all entities, all
ports, and all use cases under three global folders. There is deliberately no
`core/shared/` drawer ([ADR-0003](../adr/0003-package-layout.md)).

The dependency rule is one-directional: adapters depend on core; core depends only on
its own ports (abstract `Protocol` interfaces). Dependencies are not discovered via
globals — every outbound dependency is constructed once in a composition root and
injected into the app factory, so each test gets a fresh, isolated app.

```
                 INBOUND ADAPTERS  (drive the core)
   HTTP routes (/v1/*)     MCP tools (/mcp)     internal UDS hook router
   adapters/inbound/http   adapters/inbound/mcp adapters/inbound/internal
   POST/GET/DELETE         FastMCP tools        POST /_internal/hooks
            \                    |                      /
             \                   v                     /
              \   ┌────────────────────────────────┐ /
               -->│            mad.core             │<-
                  │  framework-free, adapter-free   │
                  │  (import-linter: no fastapi /   │
                  │   subprocess / mad.adapters)    │
                  │                                 │
                  │  use_cases/  orchestrate ports  │
                  │  domain/     entities, VOs,     │
                  │              rules (no I/O)      │
                  │  ports/      Protocol seams:     │
                  │   SessionRepository,            │
                  │   WorkspaceProvisioner,         │
                  │   AgentLauncher, EventStore,    │
                  │   EventBus, EventLogQuery,      │
                  │   TaskQueue/TaskProjection,     │
                  │   Clock, ModelCatalog           │
                  └────────────────────────────────┘
              -->         ^                ^         <-
             /            |                 \          \
   persistence/       agents/         events/ + orchestration/
   JsonlSessionRepo   ClaudeCLIProvider InMemoryEventBus
   LocalWorkspace…    OpenCodeProvider  JsonlEventLogQuery
                      factory.get_launcher InMemoryTaskProjection / SystemClock
                 OUTBOUND ADAPTERS  (implement the ports)
```

## The layers: `core` vs `adapters`

### `mad.core` — the business core (no frameworks, no I/O)

Three bounded contexts live here. Each is self-contained, with `domain/` (pure data
and rules), `ports/` (the `Protocol` seams to the outside), and `use_cases/` (the
application logic that orchestrates ports).

**`core/sessions/` — the sessions context.** The reason Mad exists: provision an
isolated workspace, mount resources (clone repos / write files), and launch an
external agent against it.

- `domain/entities/session.py` — the `Session` entity (status, workspace,
  `working_directory`, `tokens_to_redact`, `last_conversation_id`, timestamps).
- `domain/value_objects/mount_path.py` — `MountPath`, which rejects path-traversal
  escapes at construction (CLAUDE.md hard rule 3).
- `domain/exceptions/`, `domain/rehydrate.py` — typed errors and rebuild-from-log
  logic.
- `ports/outbound/` — three `Protocol` interfaces: `SessionRepository` (append-only
  event log + read path), `WorkspaceProvisioner` (`create` / `destroy` /
  `materialize_github_repo` / `materialize_file`), and `AgentLauncher`
  (`run(session_id, prompt, workspace, emit, …)`).
- `use_cases/` — `CreateSessionUseCase`, `SendUserMessageUseCase`, `GetSessionUseCase`,
  `ListSessionsUseCase`, `DeleteSessionUseCase`, `CleanupSessionsUseCase`, plus the
  `auto_sync_prompt` helper.
- `store.py` — `SessionStore`, the in-memory live-session index (`sessions` and
  `idempotency` dicts). It holds no I/O; durability is the repository's job.

**`core/events/` — the events context (observability only).** Exposes Mad's event
vocabulary verbatim over a cross-session surface; it does NOT translate, classify, or
act on events (CLAUDE.md hard rule 8, [ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md)).

- `domain/event.py`, `domain/event_id.py` — the immutable `Event` (with a UUIDv7
  `event_id`, [ADR-0005](../adr/0005-uuidv7-event-id.md)); `type` is a free-form
  string so new vocabulary needs no entity change.
- `ports/` — `EventStore` (narrow single-method `append(...) -> Event` write port),
  `EventBus` (pub/sub for live delivery, with `EventFilter`), and `EventLogQuery`
  (paginated historical reads).
- `use_cases/` — `QueryEventsUseCase` (paginated history) and `StreamEventsUseCase`
  (filtered live tail with `Last-Event-ID` replay-then-tail dedup).
- `emitter.py` — `EventEmitter`, the **single write gateway** (see below).

**`core/orchestration/` — the orchestration context.** Turns queued tasks into
launcher runs under dispatch policies, retries, and priorities
([ADR-0009](../adr/0009-orchestration-module.md)).

- `domain/` — `Task`, `dispatch_policy` / `deployment_policy`, `retry_schedule`,
  `ordering`, `model_config` / `effort_config` / `timeout_config`, and rate-limit
  exceptions.
- `ports/` — `TaskQueue` (read-side projection: `queued` / `in_flight` / `retry_info`
  / `pending_session_ids`), `TaskProjection` (`TaskQueue` plus an `apply(event)`
  write hook the dispatcher tails), `Clock`, and `ModelCatalog`.
- `use_cases/` — `Dispatcher` (the background loop), `EnqueueTaskUseCase`,
  `CancelTaskUseCase`, `ListTasksUseCase`, the deployment policy/model/effort
  bootstrap-and-set use cases, `rehydrate_pending_sessions`, and more.

### `mad.adapters` — the I/O edge

**Inbound (drive the core):**

- `adapters/inbound/http/` — the public FastAPI app. `app.py::create_app(...)` is the
  application factory; `dependencies.py` is the **composition root**; `routes/`
  contains four routers — `sessions.py`, `events.py`, `orchestration.py`,
  `providers.py`. Handlers are thin: parse the typed request, instantiate a use case
  with dependencies from `app.state`, call `execute(...)`, map the result (or domain
  exception) to an HTTP response. All request/response bodies are Pydantic models
  (CLAUDE.md hard rule 9).
- `adapters/inbound/mcp/server.py` — `build_mcp_server(...)` returns a `FastMCP`
  mounted at `/mcp` ([ADR-0010](../adr/0010-mcp-mounted-http-inbound-adapter.md)). It
  is a **peer inbound adapter**, not a layer on top of HTTP: each tool calls the same
  use case the matching HTTP route calls, in-process, against the same dependencies,
  and returns the same Pydantic model — so the two surfaces cannot drift (hard rule
  13, [ADR-0012](../adr/0012-http-mcp-tool-parity.md)). The streaming SSE surface is
  the sole carve-out.
- `adapters/inbound/internal/` — a **separate** FastAPI app
  (`create_internal_app`) bound to a Unix Domain Socket, never exposing docs/openapi.
  `hooks_router.py` accepts `POST /_internal/hooks` from `forward.sh` running inside
  each workspace, scrubs credential-shaped fields, and writes the
  `agent.<provider>.hook.*` event through the same `EventEmitter`
  ([ADR-0008](../adr/0008-internal-hook-adapter-and-vocabulary.md)).

**Outbound (implement the ports):**

- `adapters/outbound/persistence/` — `JsonlSessionRepository` (the authoritative JSONL
  session log, hard rule 6) and `LocalWorkspaceProvisioner` (clones repos, strips the
  token from the remote per hard rule 2, materializes files, deep-merges the hook
  bootstrap). Note: `JsonlSessionRepository` satisfies **two** ports at once —
  `SessionRepository` and `EventStore` ([ADR-0007](../adr/0007-single-write-gateway-event-emitter.md)).
- `adapters/outbound/agents/` — `ClaudeCLIProvider` (`claude_cli`) and
  `OpenCodeProvider` (`opencode`), the by-name extension point `factory.get_launcher`,
  the `hooks/` payloads (`forward.sh`, `settings.local.json`), `hook_socket.py`, and
  `model_catalog.py` (the `ModelCatalog` adapter).
- `adapters/outbound/events/` — `InMemoryEventBus` (bounded per-subscriber queues;
  disconnects slow subscribers per [ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md))
  and `JsonlEventLogQuery` (reads the JSONL log for history/replay).
- `adapters/outbound/orchestration/` — `InMemoryTaskProjection` (the `TaskProjection`)
  and `SystemClock` (the `Clock`).

**Entry point:** `entry_points/cli.py` implements `mad serve`. It builds the
dependencies once, constructs the public app via `create_app(...)` and the internal
app via `create_internal_app(emitter)` (sharing the **same** `EventEmitter` so hook
events appear in the public stream), and runs **two uvicorn servers** concurrently —
the public one on a TCP port, the internal one on the UDS.

## Composition root and wiring

`adapters/inbound/http/dependencies.py::build_dependencies()` constructs the
production defaults for every port — `SessionStore`, `JsonlSessionRepository`,
`InMemoryEventBus`, `EventEmitter`, `JsonlEventLogQuery`, `InMemoryTaskProjection`,
`SystemClock`, `ModelCatalogAdapter`, and the deployment policy/model/effort configs.
This is the **only** place concrete adapters are wired to ports.

`create_app(...)` accepts every dependency as an optional keyword argument, falling
back to `build_dependencies()` for any not supplied. This keyword DI is what lets
tests inject a `ScriptedLauncher` (from `tests/support/`) or fake repos without
monkey-patching production modules, and it is the seam for swapping any port in
production. `create_app` also stashes each dependency on `app.state`, registers
domain-exception → HTTP-status handlers, includes the four routers, mounts the MCP
ASGI app at `/mcp`, and runs startup work in the app lifespan: retention purge,
projection bootstrap-from-log, session rehydration, deployment-config bootstrap, and
`Dispatcher.start()` / `.stop()`.

## Request flow

A request always crosses the same boundary chain: **inbound adapter → use case
(holding injected ports) → outbound adapter(s) → `EventEmitter.emit` → `EventStore` +
`EventBus`.**

Example — `POST /v1/sessions` (the same shape applies to the `mad_create_session` MCP
tool, which reuses the identical use case and models):

1. **Inbound (HTTP route, `routes/sessions.py`).** FastAPI validates the body against
   `CreateSessionRequest`. The handler maps it to the use case's `CreateSessionInput`
   and reads dependencies off `app.state`.
2. **Use case (`CreateSessionUseCase.execute`).** Checks idempotency, validates every
   `mount_path` and the `working_directory` via the `MountPath` value object
   (hard rule 3), asks the `WorkspaceProvisioner` to create the workspace, resolves
   the agent's working directory ([ADR-0011](../adr/0011-launcher-working-directory.md)),
   emits `session.created` through the `EventEmitter`, then drives the provisioner to
   clone repos / write files. It builds the `Session`, registers it in the
   `SessionStore`, and returns.
3. **Outbound.** `LocalWorkspaceProvisioner` performs the filesystem and `git` work
   (stripping tokens from the remote, hard rule 2). `EventEmitter` persists and
   publishes the event.
4. **Response.** The handler returns the session's response model; FastAPI serializes
   it (and OpenAPI / the MCP tool schema are generated from the same Pydantic types).

Running an agent has two inbound paths that both end in the shared `_run_launcher`
coroutine in `send_user_message.py`:

- **Direct (`POST /v1/sessions/{id}/messages`).** `SendUserMessageUseCase` validates
  the session, rejects a concurrent in-flight task, resolves effective
  model/effort/timeout, emits `user.message`, and schedules the launcher run as a
  fire-and-forget `asyncio` task — the HTTP call returns `{"status": "accepted"}`
  immediately.
- **Queued (`POST /v1/tasks` → orchestration).** `EnqueueTaskUseCase` records the task
  via the emitter; the lifespan-managed `Dispatcher` (a background loop subscribed to
  the bus, feeding `TaskProjection.apply`) selects the next ready task under the active
  dispatch policy and `await`s `_run_launcher` serially (single in-flight,
  [ADR-0009](../adr/0009-orchestration-module.md)).

## Event and agent-output flow

Agent output is streamed, not buffered. The use case hands the launcher a per-run
`emit` callback (which token-redacts payloads per hard rule 2 and then calls
`EventEmitter.emit`):

1. The launcher (`ClaudeCLIProvider` / `OpenCodeProvider`) spawns the external CLI with
   `cwd=workspace`, reading stdout **line by line**.
2. Each line becomes one `emit("agent.output", {...})` call. On completion it emits
   `session.status_idle` (exit 0) or `session.error` (non-zero / timeout). Mad never
   parses tool calls or runs a conversation loop — it is infrastructure only (hard
   rule 1).
3. Every `emit` goes through `EventEmitter`, which appends to the `EventStore` (the
   JSONL log — the source of truth) and then publishes to the `EventBus`.
4. Live subscribers on `GET /v1/events/stream` receive matching events.
   `StreamEventsUseCase` subscribes to the bus first, replays from
   `JsonlEventLogQuery` when a `Last-Event-ID` is present, then tails live with a
   dedup boundary so the reconnect window is gap-free and duplicate-free
   ([ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md),
   [ADR-0005](../adr/0005-uuidv7-event-id.md)).

Hook events follow the same write path from a different inbound edge: `forward.sh`
inside the workspace `POST`s to the internal UDS app, which emits
`agent.<provider>.hook.*` through the shared `EventEmitter` — so they surface on the
public stream automatically ([ADR-0008](../adr/0008-internal-hook-adapter-and-vocabulary.md)).

## The single-write-gateway rule

`EventEmitter.emit()` is the **only** sanctioned write path to the session event log
(CLAUDE.md hard rule 11, [ADR-0007](../adr/0007-single-write-gateway-event-emitter.md)).
Its body is deliberately tiny: `append` to the `EventStore`, `publish` to the
`EventBus`, then run an optional synchronous `on_emit` hook, and return the typed
`Event`.

The discipline around it:

- **Use cases** receive `EventEmitter` as an injected dependency and call `emit()`.
  They MUST NOT call `SessionRepository.append_event` or `EventBus.publish` directly.
- **Outbound adapters** (e.g. a launcher callback) receive an `emit` *callable*
  supplied by the use case — they never touch the ports themselves.
- **Inbound adapters** (the SSE stream, the events query) only *subscribe* or *query*
  — they never write.

The `on_emit` hook is the decoupling seam: the sessions context uses it to bump
`Session.updated_at` and capture the conversation ID without the events module
importing the sessions domain, keeping the [ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md)
boundary intact. Because `JsonlSessionRepository` satisfies both `SessionRepository`
and the narrow `EventStore` port, this single gateway needs no extra adapter.

## Extension points

- **New agent provider.** Implement the `AgentLauncher` Protocol (an outbound adapter
  under `adapters/outbound/agents/`) and register it by name in
  `factory.get_launcher(provider_name)`. The session's `agent.provider` selects it at
  run time. No core change is required.
- **Swap any port implementation.** Pass it as a keyword argument to `create_app(...)`
  — a different `SessionRepository`, `WorkspaceProvisioner`, `EventBus`,
  `EventLogQuery`, `Clock`, `ModelCatalog`, `TaskProjection`, etc. This is how tests
  inject fakes and how a production deployment would, say, replace `InMemoryEventBus`
  with a cross-process bus (ports unchanged, per [ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md)).
- **New use case / endpoint.** Add the use case under the owning context's
  `use_cases/`, a thin route with Pydantic request/response models (hard rule 9), and
  the mirrored MCP tool that calls the same use case (hard rule 13 — required in the
  same change for any request/response route).
- **New event vocabulary.** `Event.type` is a free-form string; emit a new type
  through `EventEmitter` and it flows to the stream and the log with no entity or port
  change ([ADR-0004](../adr/0004-events-module-vocabulary-and-scope.md)).
- **New bounded context.** Follow the domain-first layout — its own `domain/`,
  `ports/`, `use_cases/` under `core/` — rather than a shared catch-all
  ([ADR-0003](../adr/0003-package-layout.md)).

## How the boundaries are enforced

- **`import-linter` (a forbidden-imports contract in `pyproject.toml`).** `mad.core`
  may not import `fastapi`, `mad.adapters`, `subprocess`, `shutil`, `httpx`, `boto3`,
  and friends. This is the mechanical guard for the framework-free / adapter-free core
  (hard rule 4, [ADR-0003](../adr/0003-package-layout.md)); run via `make lint`.
- **The hard rules in `CLAUDE.md`** encode the invariants this architecture rests on:
  infrastructure-only (1), framework-free core (4), events-are-observability (8),
  strongly-typed HTTP (9), single write gateway (11), and HTTP↔MCP parity (13).
- **`Protocol` interfaces at every seam.** Use cases depend on abstract ports, never
  concrete adapters, so the dependency arrow always points inward.
- **No module-level mutable globals.** `SessionStore`, the bus, idempotency maps, and
  the launcher factory are all injected through `create_app(...)`, so each app (and
  each test) is isolated ([ADR-0003](../adr/0003-package-layout.md)).
- **Test doubles live in `tests/support/`, never in `src/`.** The production package
  stays coherent on its own; fakes are injected via the factory
  ([ADR-0003](../adr/0003-package-layout.md)).
- **Contract tests** assert the parity and typing rules hold —
  `tests/integration/api/test_http_mcp_parity.py` fails if a non-stream `/v1` route
  lacks its MCP tool ([ADR-0012](../adr/0012-http-mcp-tool-parity.md)).

> Note on naming: the events use cases live at `mad/core/events/use_cases/`
> (`query_events.py`, `stream_events.py`), matching the tree in
> [ADR-0003](../adr/0003-package-layout.md). The `CLAUDE.md` key-files list refers to
> them as `core/use_cases/events/`; the on-disk path is authoritative.
