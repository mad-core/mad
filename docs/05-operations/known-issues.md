---
service: mad
domain: backend
section: operations
source_of_truth: repo
---

# Known Issues and Limitations

Known tech debt and current limitations — authored, honest. Mirror/curate from docs/08-rfcs/backlog.md and the open issues that matter to operators.

This page is for operators running a Mad instance. It lists the limitations you
will actually hit in production, plus the notable deferred work from
[`docs/08-rfcs/backlog.md`](../08-rfcs/backlog.md). It is curated, not a full backlog dump — for
the complete deferred list read the backlog directly, and for live status check
the open issues on GitHub.

## Durability and restart behavior

### Sessions and queued work are lost on restart (#93)

This is the single most important operational limitation. The agent loop runs as
an in-process `asyncio.Task` inside the FastAPI/uvicorn process (backlog item
"Sacar el harness a un worker separado"). If uvicorn restarts or crashes:

- in-flight agent runs are killed, and
- queued tasks that have not yet started are lost.

The session JSONL event log is the source of truth (CLAUDE.md hard rule 6) and
is written to disk, but on startup Mad does not currently rehydrate live state
and resume queued/in-flight tasks across a process restart. Treat a restart as
destructive to running work. Drain or finish active sessions before restarting,
and avoid `docker compose down` / image upgrades while agents are running.

Tracked as [#93](https://github.com/) (priority: high, type: bug). The broader
fix — moving the harness to a separate worker so restarts are tolerable and
sessions truly resume from the log — is backlog item "Sacar el harness (agent
loop) a un worker separado".

## Configuration

### No central settings module — env vars read ad hoc (#97)

There is no single settings module. `MAD_*` environment variables are read
directly via `os.environ` at the point of use, scattered across the codebase.
The practical impact for operators:

- there is no one file that lists every tunable and its default, and
- a typo in a variable name fails silently (the default is used) rather than
  erroring at startup.

The documented surface in [`.env.example`](../../.env.example) is the closest
thing to a complete list. Centralization is tracked in
[#97](https://github.com/) (type: refactor).

### `.env.example` lists two dead timeout variables

`.env.example` still documents these two variables:

```
# MAD_CLAUDE_CLI_TIMEOUT_S=600
# MAD_OPENCODE_TIMEOUT_S=600
```

Both are **dead**. They were superseded by a single agent-agnostic knob,
`MAD_AGENT_TIMEOUT_S` (issue #61), which is resolved at the use-case boundary
(`src/mad/core/orchestration/domain/timeout_config.py`) and passed into the
launcher. Launchers no longer read any timeout env var directly. Setting
`MAD_CLAUDE_CLI_TIMEOUT_S` or `MAD_OPENCODE_TIMEOUT_S` has **no effect**.

To change the per-run wall-clock budget, use:

1. the per-session `timeout_s` field on the create-session request, else
2. `MAD_AGENT_TIMEOUT_S` (operator default), else
3. the built-in default of 600 s.

The dead lines in `.env.example` are a documentation lag, not a feature — do not
rely on them.

### Stale coverage comment in `pyproject.toml`

The comment block in `pyproject.toml` (around the coverage policy) says the
thresholds are 95% on `src/mad/core/` and 92% on `src/mad/`. The CI gate in
`.github/workflows/ci.yml` actually enforces **94%** on `mad.core` (unit) and
**90%** on `mad` (full suite). The comment is stale; the workflow is
authoritative. No runtime impact — relevant only when reading the repo's quality
policy.

## Scope and feature limitations

### Multi-tenancy is deferred (ADR-0006)

Mad runs single-tenant: all sessions belong to whoever runs the service. There
is no `tenant_id` on sessions, no per-tenant authentication, and no scoping of
session visibility. The cross-session events surface (`GET /v1/events`,
`GET /v1/events/stream`) exposes **every** session's events as a single
firehose — there is no per-tenant filtering.

If you run Mad for more than one consumer, isolate them at the deployment level
(separate instances, separate ports — see `MAD_INSTANCE` / `MAD_HOST_PORT` in
`.env.example`). Decision and rationale:
[ADR-0006](../adr/0006-multi-tenancy-deferred.md).

### No built-in API authentication

Mad ships no authentication layer. Auth is expected at the edge — the documented
deployment puts Mad behind a Cloudflare Tunnel with Service-Token-based
Cloudflare Access (`docs/05-operations/runbooks/cloudflare-tunnel.md`). The MCP DNS-rebinding guard
(`MAD_MCP_ALLOWED_HOSTS`) is off by default for the same reason. Do **not**
expose a Mad instance directly to an untrusted network. Backlog: "API
authentication".

### OpenCode hook capture is not wired

For the `opencode` provider, the launcher exports `MAD_HOOK_SOCKET` (and
`MAD_SESSION_ID` / `MAD_PROVIDER`) to the subprocess for forward compatibility,
but OpenCode does not currently read it — the `forward.sh` hook integration is
**not** wired for OpenCode. Only the `claude_cli` provider produces
`agent.<provider>.hook.*` events. With OpenCode you get `agent.output` (raw
terminal stdout, including ANSI/spinner sequences — structured JSON parsing is
deferred) plus `session.status_idle` / `session.error`, but no structured hook
events.

### Model / effort resolution gaps

- `resolve_effective_model`'s `machine_default` parameter exists but is never
  wired to an env var. The intended `MAD_DEFAULT_MODEL` knob is **not** read at
  startup yet (backlog: "Wire `MAD_DEFAULT_MODEL` env var").
- `PUT /v1/model` stores the deployment default **unvalidated**. An invalid
  value is accepted at write time and only fails later at dispatch. Backlog:
  "Per-provider validation on `PUT /v1/model`".
- `ModelCatalogAdapter.discover()` is uncached: every model-aware
  session-create/enqueue shells out to `opencode models` (10 s timeout) with no
  TTL cache. Under load this adds a subprocess per request. Backlog: "TTL cache
  for `ModelCatalogAdapter.discover()`".
- Per-task `effort` is not yet supported (only per-session and deployment
  default). Proposed in RFC [#81](https://github.com/).

## Scaling limitations (from the backlog)

These are architectural limits that bite as the instance grows. Full write-ups
in [`docs/08-rfcs/backlog.md`](../08-rfcs/backlog.md).

- **Event log doubles as projected state.** Rehydrating state replays the full
  per-session JSONL, and `GET /v1/sessions` scans the entire sessions directory.
  This is fine for small instances but degrades past roughly 100 sessions or
  once you need filtered/paginated listings. Proposed fix: project current state
  into a `state.json` per session or a single SQLite table.
- **SSE has no `Last-Event-ID` reconnection at the stream tail.** The streaming
  surface is adequate for a local observer; robust multi-subscriber, low-latency
  fan-out (and Redis pub/sub once the harness is a separate worker) is deferred.

## Deferred capabilities

Not bugs — capabilities intentionally out of scope for the current line. From
the backlog and open feature issues:

- **Sequential multi-session workflows** — chaining agents with branch
  propagation. Tracked as feat [#90](https://github.com/) (priority: high) and
  backlog item "Multi-session workflows".
- **Docker-per-session sandbox** — ephemeral containers instead of the current
  bwrap/direct-subprocess model (see `docs/05-operations/runbooks/sandbox-bwrap.md`).
- **Encrypted vaults** for credentials instead of passing them in request JSON.
- **Scheduler / cron** for recurring sessions.
- **Web dashboard**.
- **More LLM providers** (Ollama, OpenAI, etc.); also unify the provider
  registry — `factory.get_launcher` and `model_catalog._DISCOVERY` currently
  list providers independently.

## How to check current status

GitHub issue numbers above (`#NN`) are the live source of truth for status —
some may be closed or re-prioritized after this page was written. List the open
operator-facing issues with:

```bash
gh issue list --state open --limit 50
```
