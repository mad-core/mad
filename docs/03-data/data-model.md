---
service: mad
domain: backend
section: Data
source_of_truth: repo
---

# Data Model

## Storage strategy: an append-only JSONL event log, no database

Mad has **no relational database and no NoSQL store**. There is no ORM, no
schema migration tool, no connection string anywhere in the package. The
persistent data model is an **append-only event log on the local filesystem**,
written one JSON object per line (JSONL), with **one file per session**.

This is mandated by CLAUDE.md hard rule 6: *"Source of truth is the session
log. Every action is both printed to stdout AND appended to the session log
JSONL. The log is authoritative; if the process crashes, a new harness reads
the log and resumes."*

The single write path is `emit()` in
`src/mad/adapters/outbound/persistence/jsonl_session_repository.py`, which both
prints the event to stdout and appends it to the session's `.jsonl` file:

```python
def emit(session_id, event_type, data=None) -> dict:
    event = {
        "event_id": str(new_event_id()),
        "type": event_type,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    if data:
        event.update(data)          # data is FLATTENED onto the record
    line = json.dumps(event)
    print(line)                      # stdout
    ensure_sessions_dir()
    with log_path(session_id).open("a") as f:
        f.write(line + "\n")         # append-only JSONL
    return event
```

(Source: `jsonl_session_repository.py`, `emit`.)

### Two storage tiers: durable log vs. ephemeral index

There are two distinct places session state lives, and only one is durable:

| Tier | Where | Durability | Code |
|---|---|---|---|
| Durable event log | `<sessions_dir>/<session_id>.jsonl` | Survives restarts; authoritative | `JsonlSessionRepository` (`jsonl_session_repository.py`) |
| Live in-memory index | `SessionStore.sessions: dict[str, Session]` | Per-process; lost on restart | `src/mad/core/sessions/store.py` |

`SessionStore` is explicitly documented as having **no I/O** — it is "a thin
container" holding the live `Session` objects plus an idempotency map
(`idempotency: dict[str, str]`, key → session_id). When a session is not found
in the in-memory index (e.g. after a restart), it is **rebuilt from its JSONL
log** by replaying events — see [Reconstruction](#how-a-session-is-rebuilt-from-the-log-rehydration)
below. (Source: `store.py` docstring; `rehydrate.py` docstring.)

The outbound port that abstracts the durable tier is `SessionRepository`
(`src/mad/core/sessions/ports/outbound/session_repository.py`), a `Protocol`
described in its own docstring as an *"Append-only event log for a session."*
Its production implementation is `JsonlSessionRepository`.

### The persisted record shape (one JSONL line)

Each line is a flat JSON object. The persistence layer **flattens the event
`data` payload onto the top-level record** alongside the metadata keys
(`emit` does `event.update(data)`). A line therefore looks like:

```json
{"event_id": "0192...uuidv7...", "type": "agent.output", "timestamp": "2026-06-26T20:00:00+00:00", "text": "..."}
```

- The three **metadata keys** are always `event_id`, `type`, `timestamp`.
- Everything else on the line is the event's `data`.
- **`session_id` is NOT a field on the line** — it is the file name
  (`log_path()` returns `<sessions_dir>/<session_id>.jsonl`). Readers pass the
  id in separately: `event_from_persisted(raw, session_id)`
  (`event.py`). Rehydration defensively strips `session_id` if it ever appears
  in `data` (`rehydrate.py::_event_payload`).

The `Event` entity recovers `data` by removing the metadata keys
(`_META_KEYS = {"event_id", "type", "timestamp"}` in `event.py`).

---

## Entities

The service owns three domain entities. Only **`Event`** is written to disk;
**`Session`** and **`Task`** are projections rebuilt by replaying the event log.

### Session (aggregate root)

The `Session` is the primary aggregate — "the lifecycle of a single agent
invocation from creation through running, idle, error, or deletion." It is a
**mutable** dataclass.

Source: `src/mad/core/sessions/domain/entities/session.py`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `session_id` | `str` | (required) | Unique session identifier; also the JSONL file stem. |
| `agent` | `dict[str, Any]` | (required) | Agent descriptor. Rehydration fills `{"name", "provider"}` from the `session.created` event. |
| `workspace` | `str` | (required) | Absolute path to the session workspace root on disk. |
| `working_directory` | `str` | `""` → `workspace` | Effective cwd handed to the launcher (ADR-0011). `__post_init__` defaults it to `workspace` when blank. |
| `status` | `str` | `"created"` | Lifecycle state. Transitions: `created → running → idle`, `created → running → error`, `any → deleted` (class docstring). |
| `base_branch` | `str \| None` | `None` | Git branch checked out in the cloned repo, if specified. |
| `model` | `str \| None` | `None` | Model override passed to the launcher. |
| `effort` | `str \| None` | `None` | Effort/reasoning hint passed to the launcher. |
| `timeout_s` | `float \| None` | `None` | Per-session launcher wall-clock override (issue #61). `None` = inherit operator default (`MAD_AGENT_TIMEOUT_S` env > 600 s). |
| `resources_mounted` | `list[dict[str, Any]]` | `[]` | Descriptors of repos/files mounted into the workspace. |
| `response` | `dict[str, Any]` | `{}` | Free-form response payload accumulated in memory. |
| `tokens_to_redact` | `list[str]` | `[]` (`repr=False`) | Secrets to scrub from output. **Never serialized** (absent from `to_dict`) — token hygiene, hard rule 2. |
| `dispatch_policy` | `DispatchPolicy \| None` | `None` (`repr=False`) | Per-session dispatch gating (see [Value objects](#value-objects)). `None` = inherit deployment default. |
| `manual_drain_remaining` | `int` | `0` (`repr=False`) | Count of queued tasks a `ManualPolicy` session may drain after an explicit trigger (ADR-0009 §9). |
| `priority` | `int` | `DEFAULT_PRIORITY` = `1` | Cross-session dispatch priority, `[1, 10]`, higher dispatches first (issue #46). |
| `last_conversation_id` | `str \| None` | `None` | Last conversation id returned by the launcher. **Not persisted to JSONL in v1**; `agent.conversation_started` in the log is authoritative (issue #63). |
| `created_at` | `datetime` | `now(UTC)` | Creation timestamp (tz-aware UTC). |
| `updated_at` | `datetime` | aligned to `created_at` | Last-activity timestamp; `__post_init__` aligns it to `created_at` to avoid microsecond drift. |

Notable behaviors traced to the same file:

- **Status mutators** are plain methods: `mark_running`, `mark_idle`,
  `mark_error`, `mark_deleted`.
- **`touch(timestamp)`** only advances `updated_at` if the new timestamp is
  more recent, so out-of-order replay during rehydration never pulls the clock
  backwards.
- **`to_dict()` / `from_dict()`** are serialization helpers *"for SessionStore
  compatibility"* — an in-process/API shape, **not** the durable representation.
  The Session is never written as a row; its durable form is its event stream.
  `to_dict` deliberately omits `tokens_to_redact`, `dispatch_policy`,
  `manual_drain_remaining`, and `last_conversation_id`. `from_dict` restores
  `priority` but not `dispatch_policy`.

### Event (the log record)

The `Event` is the unit actually persisted. It is a **frozen** dataclass and is
described as *"A single observation in Mad's persisted event log."*

Source: `src/mad/core/events/domain/event.py`.

| Field | Type | Meaning |
|---|---|---|
| `event_id` | `UUID \| None` | UUIDv7 minted at append time (ADR-0005). `None` for legacy lines written before UUIDv7 minting was introduced — surfaced as-is until they age out. |
| `session_id` | `str` | Owning session. Supplied by the reader from the file name, not stored on the line. |
| `type` | `str` | Event vocabulary string, deliberately free-form so new vocabulary needs no entity change (ADR-0004). See [Event types](#event-type-vocabulary). |
| `data` | `dict[str, Any]` | Event payload — everything on the line except the metadata keys. |
| `timestamp` | `datetime` | Mint time (ISO-8601 on disk). Missing timestamps default to the Unix epoch so legacy lines sort first. |

`event_from_persisted(raw, session_id)` (same file) builds an `Event` from the
flattened on-disk dict, tolerating both missing `event_id` (→ `None`) and
missing `timestamp` (→ epoch).

### Task (orchestration unit)

A `Task` is a unit of work submitted via `POST /v1/sessions/{id}/tasks`. It is a
**frozen** dataclass with **opaque content** — Mad never inspects `content`
(ADR-0009 Decision 7 / hard rule 1).

Source: `src/mad/core/orchestration/domain/task.py`.

| Field | Type | Default | Meaning |
|---|---|---|---|
| `task_id` | `UUID` | (required) | Task identifier. |
| `session_id` | `str` | (required) | Owning session. |
| `content` | `str` | (required) | Opaque prompt/content handed to the launcher verbatim; never parsed by Mad. |
| `scheduled_for` | `str` | (required) | Free-form schedule hint in v1: `"now"`, `"next_window"`, or an ISO-8601 timestamp. |
| `created_at` | `datetime` | (required) | Submission time; used as the FIFO/ordering key. |
| `model` | `str \| None` | `None` | Per-task model override. |
| `conversation_mode` | `Literal["new", "resume"]` | `"new"` | Whether the task starts a fresh conversation or resumes one. |

State is **not** carried on the entity (task.py docstring). The full state
history lives in the JSONL log as `task.queued → task.dispatched →
task.{completed,cancelled,failed}`; a separate in-memory projection places a
live task in either the per-session `queued` list or the `in_flight` slot.

---

## Value objects

### MountPath — path-traversal safety

`MountPath` is a `frozen` dataclass wrapping a single `value: str`. It enforces
CLAUDE.md hard rule 3 (path-traversal prevention) **at construction time**:
constructing an invalid path raises `PathTraversalError` before any filesystem
operation can run.

Source: `src/mad/core/sessions/domain/value_objects/mount_path.py`.

Validation rules (`_validate`):

- The path **must be absolute** (start with `/`), else `PathTraversalError(..., "must be absolute")`.
- `..` segments are resolved against a stack; popping past the root raises
  `PathTraversalError(..., "escapes workspace")`.
- The resolved logical path must equal `/workspace` (`WORKSPACE_PREFIX`) or sit
  under `/workspace/`, else `PathTraversalError(..., "escapes workspace")`.

This is the canonical implementation; `security.validate_mount_path` delegates
here (per the file docstring).

### Dispatch policy value objects

`Session.dispatch_policy` holds one of a closed union of frozen value objects
(`src/mad/core/orchestration/domain/dispatch_policy.py`):

- **`ImmediatePolicy`** (`kind="immediate"`) — default; dispatch as soon as work exists.
- **`WorkWindowPolicy`** (`kind="work_window"`) — dispatch only inside one of its
  `Window` value objects.
- **`ManualPolicy`** (`kind="manual"`) — queue accumulates; only an explicit
  trigger drains it.

A **`Window`** is a frozen value object: `start: time`, `end: time`,
`timezone: ZoneInfo`, `days: frozenset[Weekday]` (defaults to all seven). It can
wrap midnight (when `end <= start`) and is evaluated tz-aware via `contains()`.
`Weekday` is a `StrEnum` (`mon`..`sun`). `policy_from_dict` / `policy_to_dict`
convert between these and the HTTP discriminated-union shape.

`priority` bounds live in `src/mad/core/orchestration/domain/ordering.py`:
`MIN_PRIORITY = 1`, `MAX_PRIORITY = 10`, `DEFAULT_PRIORITY = 1`, validated by
`validate_priority`.

### Domain exceptions

Source: `src/mad/core/sessions/domain/exceptions/base.py` (re-exported from
`exceptions/__init__.py`).

| Exception | Base | Raised when |
|---|---|---|
| `DomainError` | `Exception` | Base class for all sessions-domain errors. |
| `PathTraversalError` | `DomainError` | A `mount_path` would escape the workspace (carries `mount_path`, `reason`). |
| `SessionNotFound` | `DomainError` | A session is absent from both the in-memory index and the JSONL log (carries `session_id`). |

Two orchestration errors subclass `ValueError` so the HTTP app maps them to 422
without a bespoke handler: `InvalidDispatchPolicy` (`dispatch_policy.py`) and
`InvalidPriority` (`ordering.py`).

---

## The `event_id` strategy: UUIDv7 (ADR-0005)

Every event gets a **UUIDv7** `event_id` minted at append time by
`new_event_id()` in `src/mad/core/events/domain/event_id.py`. The bit layout
(RFC 9562 §5.7), per the file:

```
48 bits — Unix milliseconds
 4 bits — version (always 0b0111 = 7)
12 bits — random
 2 bits — variant (always 0b10 = RFC 4122)
62 bits — random
```

**Why time-ordered ids matter here.** Because the first 48 bits are a
Unix-millisecond timestamp, the textual form is **lexicographically sortable in
mint-time order across files and processes**. This is exactly what the SSE
reconnect protocol needs: a client re-sends the last `id:` it saw in the
`Last-Event-ID` header, and the server replays events whose ids are *strictly
greater*. Mad writes one JSONL file per session and merges them into a
cross-session live tail, so ids must be **comparable across files** without a
global counter (ADR-0005 Context). The random tail gives collision resistance
without coordination.

Rejected alternatives (ADR-0005): UUIDv4 (non-monotonic — breaks Last-Event-ID),
per-session autoincrement (doesn't sort across sessions), JSONL line offset
(tied to filesystem layout; invalidated by rotation). There is **no backfill**:
pre-existing lines carry `event_id: null`, and the `Event` entity / query layer
surface them as-is until they age out.

The helper is pure stdlib (`secrets` + `time`), no runtime dependency, and is
slated to be replaced by `uuid.uuid7()` once Python 3.14+ ships it.

---

## How a Session is rebuilt from the log (rehydration)

When a session is not in the live in-memory index — the normal case after a
process restart — its `Session` is reconstructed by **replaying its event
stream**. This is what makes the JSONL log authoritative (hard rule 6).

Source: `src/mad/core/sessions/domain/rehydrate.py`,
`rehydrate_from_events(session_id, events) -> Session`. It is a **pure domain
helper** (no I/O, no port dependencies); callers read events from a
`SessionRepository` and pass them in. It is used by `GetSession` and
`ListSessions` (rehydrate.py docstring).

The replay folds the event stream into a minimal `Session`:

| Event type | Effect on the rebuilt Session |
|---|---|
| `session.created` | Sets `agent = {"name", "provider"}`, `working_directory`, `model`, `effort`, `timeout_s`; anchors `created_at`. |
| `session.status_running` | `status = "running"` |
| `session.status_idle` | `status = "idle"` |
| `session.error` | `status = "error"` |
| `session.deleted` | `status = "deleted"` |
| `dispatch_policy.updated` | Rebuilds `dispatch_policy` via `policy_from_dict` (malformed payload → keep current). |
| `dispatch_policy.cleared` | Resets `dispatch_policy = None` (inherit deployment default). |
| `dispatch_priority.updated` | Rebuilds `priority` via `validate_priority` (invalid → keep current). |

Timestamp rules: `created_at` is the `session.created` event's timestamp (or the
earliest event if none present); `updated_at` is the latest event's timestamp.
Events with an unparseable timestamp are skipped for the timestamp computation
but still drive status transitions.

The reconstruction is intentionally **minimal**: it does not restore
`workspace`, `resources_mounted`, `response`, `tokens_to_redact`, or
`last_conversation_id` — those are live in-memory concerns, and
`last_conversation_id` recovery across restarts is explicitly deferred
(issue #63; session.py).

---

## Event type vocabulary

`Event.type` is a free-form string; the events module emits Mad's vocabulary
**verbatim** (ADR-0004) and does not translate or classify it. The literals
emitted in `src/mad` today:

- **Session lifecycle:** `session.created`, `session.status_running`,
  `session.status_idle`, `session.error`, `session.deleted`.
- **User input:** `user.message`.
- **Agent stream:** `agent.output`, `agent.conversation_started`,
  `agent.conversation_resume_skipped`.
- **Agent hooks:** `agent.<provider>.hook.<HookEvent>` — built by
  `forward.sh` as `agent.${MAD_PROVIDER:-unknown}.hook.${EVENT}` (ADR-0008).
  `<HookEvent>` is the claude-cli hook name from
  `src/mad/adapters/outbound/agents/hooks/settings.local.json`: `SessionStart`,
  `SessionEnd`, `UserPromptSubmit`, `Stop`, `StopFailure`, `PreToolUse`,
  `PostToolUse`, `PostToolUseFailure`, `SubagentStart`, `SubagentStop`,
  `TaskCreated`, `TaskCompleted`, `Notification`.
- **Orchestration / tasks:** `task.queued`, `task.dispatched`, `task.completed`,
  `task.cancelled`, `task.failed`, `task.deferred`, `task.retrying`,
  `task.queued_for_window`.
- **Dispatch config:** `dispatch_policy.updated`, `dispatch_policy.cleared`,
  `dispatch_priority.updated`.

(Source: literal scan of `src/mad/**/*.py`, `forward.sh`, and
`settings.local.json`. New types can be added without changing the `Event`
entity — `type` is deliberately a free string.)

---

## On-disk layout

### Session logs

Source: `jsonl_session_repository.py`.

| Aspect | Value | Resolved by |
|---|---|---|
| Directory | `$MAD_SESSIONS_DIR` if set, else `./sessions/` | `sessions_dir()` (read on every call, not frozen at import) |
| File per session | `<sessions_dir>/<session_id>.jsonl` | `log_path(session_id)` |
| Reserved streams | ids starting with `__` (e.g. the deployment-wide dispatch-policy log) | excluded from `list_session_ids()` and from purge |
| Retention | `$MAD_SESSIONS_RETENTION_DAYS` (positive int) | `resolve_retention_days()`; unset/0/negative ⇒ keep forever |

Retention purging (`purge_expired_logs`) deletes a log only when its **last**
event timestamp predates `now - retention_days`, so an actively-appended log is
never deleted out from under a live session.

### Workspaces

Source: `src/mad/adapters/outbound/persistence/local_workspace_provisioner.py`.

| Aspect | Value | Resolved by |
|---|---|---|
| Base directory | `$MAD_WORKSPACE_DIR` (verbatim, no `~`/`$VAR` expansion), else `~/mad`, else `tempfile.gettempdir()` | `_workspace_base()` |
| Per-session workspace | `<base>/mad_<session_id>/` | `workspace_path(session_id)` |
| Mount resolution | `mount_path` resolved under the workspace, stripping a leading `/workspace/` | `_resolve_mount()` |

Workspace materialization side effects (same file):

- `materialize_github_repo` clones a repo into the mount, then **strips the
  token from the remote** (`git remote set-url origin <url-without-token>`,
  hard rule 2), optionally checks out `base_branch`, and installs Claude Code
  hooks.
- `_install_claude_hooks` writes `.claude/hooks/forward.sh` (mode `0755`) and
  `.claude/settings.local.json` from package resources, deep-merging into any
  existing `settings.local.json` (ADR-0011) and refusing to overwrite malformed
  JSON (`MalformedSettingsLocalJson`). Both are added to `.git/info/exclude` so
  they are never committed upstream.
- `materialize_file` writes literal file content to a mount.

The workspace is **scratch space**, not part of the durable data model: it holds
the cloned repo and agent working files, and `destroy()` removes it
(`shutil.rmtree`). The authoritative record of everything that happened remains
the JSONL event log.

---

## Known boundaries

- **No database.** The only persistence is the per-session JSONL event log on
  the local filesystem. There is no relational store, no DynamoDB single-table
  design, no document database. Scaling, indexing, and cross-session queries are
  served by reading and merging JSONL files (and the `event_id` lex-sort), not
  by a query engine.

- **Multi-tenancy is deferred (ADR-0006).** There is **no `tenant_id`** on the
  `Event` or `Session` entity, no tenant filter on the event bus or query port,
  and no per-tenant SSE channel. Today's data really is single-tenant. The
  decision will be revisited when Mad itself gains tenants (likely alongside an
  auth layer or the orchestration module). Operators running multiple tenants
  must isolate them at the **deployment boundary** (separate `make serve`
  instances, separate `MAD_SESSIONS_DIR` / `MAD_WORKSPACE_DIR`), not within the
  application.

- **Legacy `event_id: null`.** Events written before UUIDv7 minting carry a null
  id and are surfaced as-is; there is no backfill (ADR-0005). Consumers must
  treat a null id as "older than any known id."

- **`last_conversation_id` is not durable in v1.** It is held in memory only;
  cross-restart recovery is deferred to issue #63. The authoritative record is
  the `agent.conversation_started` event in the log.
