---
service: mad
domain: backend
section: rfcs
source_of_truth: repo
---

# Backlog — Mad

Things identified as improvements but out of scope for v0.1. Addressed when they
start to hurt, or once the foundation is stable.

This file is the **pre-RFC inbox**: a lower-ceremony landing spot for ideas that
haven't earned a numbered RFC yet. When an item is picked up for real work, it
graduates to a numbered `NNNN-slug.md` RFC (design still open) or an ADR (a
decision has been made) — it does not stay here once someone starts building it.

## Architecture

### 1. Separate the event log from projected state
**Problem:** re-reading the full JSONL to reconstruct state on every recovery
conflates two responsibilities (the immutable log vs. current state) and scales
poorly as sessions grow. On top of that, `GET /v1/sessions` has to scan the
entire directory.

**Proposal:** keep the JSONL as an append-only, immutable event log, but project
current state (status, turn, cursor, stop_reason, metadata) into:
- a `state.json` per session, or
- a single SQLite table (`sessions`) with one row per session.

SQLite additionally enables queries to list, filter, and paginate sessions
without touching the filesystem.

**Impact:** necessary before supporting >100 sessions or listing filters.

---

### 2. Move the harness (agent loop) to a separate worker
**Problem:** today the agent loop runs as an `asyncio.Task` inside the FastAPI
process. If uvicorn restarts or crashes, every in-flight session is lost. The
claim "the harness is stateless and resumes from the log" only truly holds if
the harness is a separate process.

**Proposal:**
- An independent worker process (subprocess, systemd unit, or container) that
  consumes work.
- A lightweight queue: Redis + `arq`, or even a `jobs` table in SQLite with
  polling.
- The API only writes `user.message` events and enqueues; the worker runs the
  loop and writes the `agent.*` events to the log.

**Impact:** makes the system restart-tolerant and unlocks real concurrency
across sessions.

---

### 3. Pub/sub for the SSE stream
**Problem:** the SSE endpoint reads the JSONL with tail-follow. That works for a
local client, but it doesn't handle reconnection well (no `Last-Event-ID`),
multiple subscribers per session, or low latency if the log lives on slow disk.

**Proposal:**
- In-memory: an `asyncio.Queue` per `session_id`, with a fallback to reading the
  file for `Last-Event-ID` reconnection (read from the given offset).
- External: Redis pub/sub once the harness is a separate process (see item 2).
- Implement the `Last-Event-ID` header that the EventSource client sends
  automatically on reconnect.

**Impact:** necessary once there's a web client or multiple observers per
session.

---

## Deprecations

### Remove inline `authorization_token` — Stage 2 (target v0.6.0)
**Context:** issue #89 moved the GitHub clone PAT to the host `GITHUB_TOKEN` /
`GH_TOKEN` environment variable. Stage 1 (shipped) keeps the inline
`authorization_token` field on the `github_repository` resource mount accepted
but marks it `deprecated=True` in the request/MCP model and emits a
`DeprecationWarning` when supplied. Inline still takes precedence over the host
env var during the deprecation window.

**Stage 2 (target v0.6.0, a deliberate minor):** remove the
`authorization_token` field from `ResourceRequest` / `ResourceSpec` and the MCP
tool input, drop the deprecation warning, and source the clone credential
exclusively from the host env var. This is a breaking change to the request
shape — gate it behind a `BREAKING CHANGE:` footer / `workflow_dispatch`
`release_kind: minor` per hard rule 12. `test_http_mcp_parity.py` stays green
(no route change); the field removal only changes the body schema.

---

## Other

- **Docker sandbox** — replace the bwrap/direct-subprocess model with ephemeral
  containers.
- **Encrypted vaults** for credentials instead of passing them in request JSON.
- **Multi-session workflows** chaining agents.
- **Scheduler/cron** for launching recurring sessions.
- **API authentication**.
- **Web dashboard**.
- **More LLM providers** (Ollama, OpenAI, etc).
- **Unify provider registry** — `factory.get_launcher` and
  `model_catalog._DISCOVERY` currently list providers independently; unify them
  into a single source of truth so adding a provider in one place is
  sufficient.
- **TTL cache for `ModelCatalogAdapter.discover()`** — every model-set
  session-create/enqueue shells out to `opencode models` (10 s timeout,
  uncached); add a short-lived in-process TTL cache to avoid repeated
  subprocesses per request.
- **Wire `MAD_DEFAULT_MODEL` env var** — `resolve_effective_model`'s
  `machine_default` parameter is defined but never passed from the
  environment; wire it to a `MAD_DEFAULT_MODEL` env var read at startup.
- **Evaluate `opencode run --output-format json` NDJSON streaming** — raw
  terminal stdout (ANSI/spinners) is streamed verbatim today; structured JSON
  output would let Mad parse and re-emit structured events instead of opaque
  text.
- **Per-provider validation on `PUT /v1/model`** — the deployment default model
  is stored unvalidated and can fail at dispatch time if the value is not in
  any provider's catalog; add provider-aware validation at write time.
