---
service: mad
domain: backend
section: Configuration
source_of_truth: repo
---

# Configuration

Mad is configured entirely through **environment variables**. There is **no central
settings/config class** today: every value is read ad hoc at its point of use via
`os.environ` / `os.getenv` (or, for the hook forwarder, a shell `${VAR}` read), scattered
across the adapters that need it. There is no `Settings` Pydantic model, no `config.py`
aggregator, and no validation layer that loads the whole surface at startup. The
human-facing catalog of the operator-tunable subset is [`.env.example`](../../.env.example);
the compose-interpolation and build subset is described in
[`compose.example.yml`](../../compose.example.yml) and the [`Dockerfile`](../../Dockerfile).

> **Planned follow-up.** Centralizing all environment-variable access into a single typed
> settings module (one load-and-validate boundary instead of scattered `os.environ` reads)
> is tracked in [#97](https://github.com/mad-core/mad/issues/97). Until then, the tables below are the authoritative inventory,
> traced to each call site in the code.

This document enumerates **every** environment variable any part of the service reads or
writes, grouped by role. Each row cites where the value is consumed.

## How to read these tables

- **Type** — the logical type the code coerces the raw string into (the environment value is
  always a string).
- **Default** — the value used when the variable is unset, empty, or (where noted) malformed.
- **Required** — whether the service needs it to function. Almost everything is optional with
  a safe default; the few conditionally-required entries are credentials.
- **Read at** — the source location (repo-relative `path:line`) where the value is consumed.

---

## 1. Runtime `MAD_*` tunables (read by the application)

These are the operator knobs Mad's own Python reads at runtime. All are optional and fall
back to a safe default.

| Variable | Purpose | Type | Default | Required | Read at |
|---|---|---|---|---|---|
| `MAD_AGENT_TIMEOUT_S` | Operator default wall-clock budget (seconds) for each external agent run — applied to both the primary run and the post-run auto-sync run. A per-session override (`timeout_s` in the create-session request) takes precedence; precedence is `session timeout_s` > `MAD_AGENT_TIMEOUT_S` > `600`. | float (seconds) | `600` (also used when the value is empty or non-numeric) | No | `src/mad/core/orchestration/domain/timeout_config.py:60` (`env_timeout_s()`); resolved in `src/mad/core/sessions/use_cases/send_user_message.py:99-101` and `src/mad/core/orchestration/use_cases/dispatcher.py:367-369` |
| `MAD_SESSIONS_DIR` | Directory holding the per-session JSONL event logs — the source of truth (CLAUDE.md hard rule 6) and the backing store the events query/SSE reads history from. | filesystem path | `sessions` (relative to the process CWD) | No | `src/mad/adapters/outbound/persistence/jsonl_session_repository.py:34` (`sessions_dir()`); same dir consumed by `src/mad/adapters/outbound/events/jsonl_event_log_query.py:35` |
| `MAD_SESSIONS_RETENTION_DAYS` | Retention TTL (days) for purging old JSONL logs once at app startup. Unset / non-integer / zero / negative all disable purging (keep every log forever — the historical safe default). | int (days) | unset → retention **disabled** | No | `src/mad/adapters/outbound/persistence/jsonl_session_repository.py:91` (`resolve_retention_days()`); enforced in the app lifespan at `src/mad/adapters/inbound/http/app.py:185` |
| `MAD_SSE_HEARTBEAT_S` | Interval (seconds) between transport-level keepalive `: ping` frames on `GET /v1/events/stream`, so buffering proxies flush the stream. Missing, unparseable, or non-positive values fall back to the default. | float (seconds) | `15` | No | `src/mad/adapters/inbound/http/routes/events.py:73` (`_heartbeat_interval()`) |
| `MAD_MCP_ALLOWED_HOSTS` | Comma-separated `Host`-header allowlist. Setting it enables MCP DNS-rebinding protection on `/mcp` scoped to those hosts; leaving it empty keeps protection **off** (the deliberate posture — auth is expected at the Cloudflare edge, ADR-0010). | comma-separated string | empty → protection **OFF** | No | `src/mad/adapters/inbound/mcp/server.py:159` |
| `MAD_WORKSPACE_DIR` | Base directory under which each session's isolated workspace is created. Used verbatim — **no** `~` or `$VAR` expansion; empty/whitespace is treated as unset. | filesystem path | `~/mad`, then `tempfile.gettempdir()` if the home dir cannot be resolved. **In Docker it is pinned to `/workspaces`** by `Dockerfile:80` (`ENV`) and `compose.example.yml:44` (`environment:`), which override any `.env` value. | No | `src/mad/adapters/outbound/persistence/local_workspace_provisioner.py:35` (`_workspace_base()`) |
| `MAD_CLAUDE_CLI_BIN` | Path or name of the `claude` CLI binary the `claude_cli` launcher spawns. | string (path or name on `PATH`) | `shutil.which("claude")` (resolves `claude` on `PATH`) | No — but the resolved binary must exist; a missing binary emits `session.error` | `src/mad/adapters/outbound/agents/claude_cli.py:94` |
| `MAD_OPENCODE_BIN` | Path or name of the `opencode` CLI binary the `opencode` launcher spawns; also used to discover the OpenCode model catalog. | string (path or name on `PATH`) | `shutil.which("opencode")` (resolves `opencode` on `PATH`) | No | `src/mad/adapters/outbound/agents/opencode.py:49`; `src/mad/adapters/outbound/agents/model_catalog.py:29` |
| `MAD_HOOK_SOCKET` | Unix Domain Socket path where the internal hook-ingestion uvicorn listens and `forward.sh` POSTs claude-cli hook events (ADR-0008). | filesystem path | `$XDG_RUNTIME_DIR/mad/hooks.sock`, else `/tmp/mad/hooks.sock` | No | `src/mad/adapters/outbound/agents/hook_socket.py:14` (`resolve_hook_socket_path()`); used to bind the internal server at `src/mad/entry_points/cli.py:93` |

---

## 2. System / infrastructure variables (read by the application)

Standard OS-provided variables Mad reads but does not own. Operators rarely set these
directly.

| Variable | Purpose | Type | Default | Required | Read at |
|---|---|---|---|---|---|
| `XDG_RUNTIME_DIR` | Standard freedesktop per-user runtime dir; used only to derive the **default** `MAD_HOOK_SOCKET` base path when that variable is unset. | filesystem path | falls back to `/tmp` when unset | No (usually set by the OS / login session) | `src/mad/adapters/outbound/agents/hook_socket.py:8`; referenced in CLI help at `src/mad/entry_points/cli.py:42` |
| `PATH` | Standard executable search path. Mad copies and **augments** it for spawned agents — appending `/usr/local/bin`, `/usr/bin`, `/bin`, and the current interpreter's directory — so agent shebangs resolve even under a restricted `PATH`. | `os.pathsep`-delimited list | inherited from the process; augmented, never required | No | `src/mad/adapters/outbound/agents/_subprocess.py:54-62` |

---

## 3. Variables Mad *exports* to the agent subprocess

Mad **sets** (does not read for its own behavior) these on the launched agent's environment.
Operators should **not** set them — Mad overwrites them per launch. They are listed for
completeness because they appear in the process environment and are consumed by `forward.sh`
and the agent CLI.

| Variable | Purpose | Value Mad sets | Set at / read by |
|---|---|---|---|
| `MAD_SESSION_ID` | Session attribution for hook payloads — lets `forward.sh` tag each hook event with the originating session. | the live session id | Set at `src/mad/adapters/outbound/agents/claude_cli.py:108` and `src/mad/adapters/outbound/agents/opencode.py:63`; read by `src/mad/adapters/outbound/agents/hooks/forward.sh:7,14` |
| `MAD_PROVIDER` | Provider segment in the `agent.<provider>.hook.*` event type vocabulary. | `claude_cli` or `opencode` | Set at `claude_cli.py:110` / `opencode.py:65`; read by `forward.sh:15` |
| `MAD_HOOK_SOCKET` | The UDS path `forward.sh` POSTs hook events to (also a tunable in §1 — Mad re-exports the resolved value so the subprocess inherits it). | the resolved socket path | Exported at `claude_cli.py:109` / `opencode.py:64`; read by `forward.sh:20` |
| `CLAUDE_CODE_MAX_RETRIES` | Disables the claude CLI's own retry loop so Mad owns the full retry schedule and can emit `task.retrying` with correct backoff. | `"0"` | Set at `src/mad/adapters/outbound/agents/claude_cli.py:113` |

---

## 4. Credentials & secrets

These hold sensitive material. **Document the key only — never echo, log, or commit the
value.** None of them are read by Mad's own Python: they live in the container/process
environment and are consumed by the **launched agent** and its SDKs (the claude CLI, `git`,
the AWS SDK). The operator surface for them is `.env.example` (some are commented out there).

| Variable | Secret? | Purpose | Default | Required | Notes / consumed by |
|---|---|---|---|---|---|
| `GITHUB_TOKEN` | **Secret** | GitHub token the **launched agent** reads to push commits and open PRs from inside the workspace during auto-sync. | none | Conditional — only when you want the agent to push / open PRs | Referenced by the auto-sync prompt at `src/mad/core/sessions/use_cases/auto_sync_prompt.py:49`; documented in `.env.example`. This is **not** the clone token (see Token hygiene below). |
| `GH_TOKEN` | **Secret** | Alias accepted alongside `GITHUB_TOKEN` for the same push/PR purpose (the auto-sync prompt names both). | none | Conditional — same as `GITHUB_TOKEN` | Same call site (`auto_sync_prompt.py:49`) and `.env.example`. |
| `ANTHROPIC_API_KEY` | **Secret** | API-key billing for the `claude` CLI as an alternative to a Pro/Max login. Read by the claude CLI itself, not by Mad. | none | Conditional — only if **not** using a persisted Pro/Max login (the documented default path) | Commented in `.env.example`; the recommended alternative is logging in once inside the container so `~/.claude` persists. |
| `AWS_ACCESS_KEY_ID` | **Secret** | AWS access key for the launched agent's AWS SDK usage (e.g. Bedrock). | none | No (optional) | Commented in `.env.example`; the default path mounts `~/.aws` read-only via compose instead of passing env. |
| `AWS_SECRET_ACCESS_KEY` | **Secret** | AWS secret key paired with `AWS_ACCESS_KEY_ID`. | none | No (optional) | Same as above. |
| `AWS_REGION` | Not secret | AWS region for the launched agent's AWS SDK calls. | none | No (optional) | Commented in `.env.example`. |

**Secret-handling guarantees in the code.** Mad never reads these tokens into its own logic,
so it cannot log them. In addition:

- **Token hygiene (CLAUDE.md hard rule 2).** The token used to **clone** a repository is a
  *different*, per-request token supplied in the create-session call — never the
  `GITHUB_TOKEN` / `GH_TOKEN` above. After cloning, Mad strips it from the git remote
  (`git remote set-url origin <url-without-token>`) and never persists it to the workspace,
  the session log, or stdout.
- **Prompt instruction.** The auto-sync prompt explicitly instructs the agent that any
  GitHub token must come from the environment and must never be written to the workspace,
  the session log, or stdout (`auto_sync_prompt.py:48-50`).
- **stderr scrubbing.** Agent stderr is redacted before it is emitted: `sk-ant-…` values and
  `token`/`key`/`secret`/`password` patterns are replaced with `[REDACTED]`
  (`src/mad/adapters/outbound/agents/_subprocess.py:41-44`).

---

## 5. Compose / instance / build variables

These drive Docker Compose interpolation and the image build. They are **not** read by Mad's
Python at runtime — they are consumed by `compose.example.yml` (instance identity, port
mapping, env injection) and the `Dockerfile` (build args). Defaults below are the
compose/Dockerfile fallbacks.

| Variable | Purpose | Type | Default | Required | Read at |
|---|---|---|---|---|---|
| `MAD_INSTANCE` | Instance name. Drives the container name (`mad-<MAD_INSTANCE>`) and the host bind-mount paths (`./instances/<MAD_INSTANCE>/…`), so each instance gets its own workspace and credential dirs. | string | `default` | No | `compose.example.yml:31,51,54,56` |
| `MAD_HOST_PORT` | Host port published for this instance's HTTP/MCP API (the container always listens on `8000`). Give each instance a distinct port. | int (port) | `8080` | No | `compose.example.yml:46` |
| `MAD_VERSION` | `mad-bros` version baked into the image and used as the image tag. Empty installs the latest published release; pin (e.g. `0.5.11`) to tie the image to an exact version. | string (version or empty) | empty → latest published | No | `compose.example.yml:20,26` (image tag + build arg); `Dockerfile:53,56` (`ARG MAD_VERSION`) |
| `PUID` | Host operator's UID. The in-container `mad` user is created with this id so the bind-mounted workspace stays writable and host-owned. | int (uid) | `1000` | No | `compose.example.yml:29` (build arg); `Dockerfile:65,70-73` (`ARG PUID`) |
| `PGID` | Host operator's GID, paired with `PUID` for the in-container `mad` user/group. | int (gid) | `1000` | No | `compose.example.yml:30` (build arg); `Dockerfile:66,70-73` (`ARG PGID`) |

> `MAD_WORKSPACE_DIR` also appears in this layer: `compose.example.yml:44` and `Dockerfile:80`
> pin it to `/workspaces` inside the container, overriding any `.env` value. See §1 for the
> code-level default (`~/mad`).

---

## 6. Serve-time variables (Makefile / CLI)

These configure where the server binds. They are **not** read via `os.environ` in Python —
they are `make` variables (overridable from the environment when invoking `make`) passed
through to uvicorn, or CLI flags on `mad serve`.

| Variable | Purpose | Type | Default | Required | Read at |
|---|---|---|---|---|---|
| `HOST` | Bind address for the dev server. A `make` variable forwarded to `uvicorn --host`. The equivalent CLI flag is `mad serve --host`, whose own default is `0.0.0.0`. | string (host/IP) | `0.0.0.0` | No | `Makefile:6,64`; CLI flag default at `src/mad/entry_points/cli.py:53` |
| `PORT` | Bind port for the dev server. A `make` variable forwarded to `uvicorn --port`. The equivalent CLI flag is `mad serve --port`, whose own default is `8000`. | int (port) | `8000` | No | `Makefile:7,64`; CLI flag default at `src/mad/entry_points/cli.py:54` |

---

## 7. Documentation drift — variables in `.env.example` that are no longer read

The following variables appear in [`.env.example`](../../.env.example) but are **inert**: no
code path reads them. They are flagged here so operators do not rely on them, and as cleanup
to reconcile.

| Variable | Status | Replacement | Evidence |
|---|---|---|---|
| `MAD_CLAUDE_CLI_TIMEOUT_S` | **Not read by any code.** Listed in `.env.example:68`; setting it has no effect. | `MAD_AGENT_TIMEOUT_S` (the single agent-agnostic timeout knob, issue #61). | Survives only in a docstring describing what it replaced: `src/mad/core/orchestration/domain/timeout_config.py:4`. A full-tree grep finds no `os.environ`/`os.getenv` read of this name. |
| `MAD_OPENCODE_TIMEOUT_S` | **Not read by any code.** Listed in `.env.example:69`; setting it has no effect. | `MAD_AGENT_TIMEOUT_S`. | Same as above (`timeout_config.py:4`); no runtime read exists. |

---

## Quick reference: precedence chains

- **Agent run timeout:** per-session `timeout_s` (create-session request body) > `MAD_AGENT_TIMEOUT_S` env > `600` s hard default.
- **Session log directory:** `MAD_SESSIONS_DIR` (if set and non-blank) > `sessions` (relative to CWD).
- **Workspace base:** `MAD_WORKSPACE_DIR` (verbatim, if set and non-blank) > `~/mad` > system temp dir. In Docker, forced to `/workspaces` by the image/compose.
- **Hook socket path:** `MAD_HOOK_SOCKET` > `$XDG_RUNTIME_DIR/mad/hooks.sock` > `/tmp/mad/hooks.sock`.
- **Agent binaries:** `MAD_CLAUDE_CLI_BIN` / `MAD_OPENCODE_BIN` (if set) > `PATH` lookup of `claude` / `opencode`.
- **MCP DNS-rebinding protection:** `MAD_MCP_ALLOWED_HOSTS` set → ON (scoped to those hosts); empty/unset → OFF.
