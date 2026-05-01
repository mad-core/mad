# CLAUDE.md — Mad

Project conventions and hard rules for anyone (human or Claude) working in this repo.

## What this project is

**Mad** (Multi Agent Develop) is a self-hosted infrastructure layer that provisions isolated workspaces, clones GitHub repositories, and launches external autonomous agents (Claude Code, OpenCode, Codex, etc.) against them. Mad streams each agent's stdout as `agent.output` events and reports when the agent finishes. Mad does NOT manage agent loops, execute tools, or parse LLM responses — external agents bring their own harnesses.

## Hard rules — never break these

1. **Infrastructure only.** Mad launches external agents, streams their stdout as `agent.output` events, and reports completion. Mad NEVER parses tool calls, NEVER executes tools, and NEVER manages a conversation loop. External tools (Claude Code, OpenCode, Codex) bring their own harnesses.

2. **Token hygiene.** GitHub tokens are used only for `git clone`, then stripped from the remote with `git remote set-url origin <url-without-token>`. They MUST NOT be persisted to the workspace, the session log, or stdout.

3. **Path traversal prevention.** `mount_path` values from requests are mapped to subdirectories of the session workspace. Absolute paths that would escape the workspace MUST be rejected before any filesystem operation.

4. **Package layout.** Core logic lives in the `mad` package under `src/mad/`, split by concern:
   - `mad.api` — FastAPI app + routers. Thin HTTP layer only: parse, validate, delegate. Exposes `create_app(store=...)` as a factory.
   - `mad.core` — pure domain. Session registry, JSONL session log (hard rule 6), workspace management, path validation (hard rule 3), token hygiene (hard rule 2). No FastAPI imports here.
   - `mad.providers` — `AgentLauncher` Protocol, `get_launcher` factory, and one module per implementation (`claude_cli`, `fake`).

   No module-level mutable globals. Session registries, SSE queues, and idempotency maps live on a `SessionStore` injected into `create_app()` so every test builds its own isolated instance. The project MUST remain `pip install -e .` compatible at all times — `pyproject.toml` owns package metadata, dependencies, and the `mad` console script.

5. **Fake launcher in tests.** Tests NEVER hit the real `claude` CLI or GitHub. They use `FakeLauncher` (from `mad.providers.fake`) with scripted event sequences and local bare repos. CI has no secrets.

6. **Source of truth is the session log.** Every action is both printed to stdout AND appended to the session log JSONL. The log is authoritative; if the process crashes, a new harness reads the log and resumes.

## Commit policy

Claude commits automatically whenever a version is "apparently stable". This is a standing instruction — no per-commit approval needed.

A state is **apparently stable** when:
- `pytest -q` exits 0 (all tests green).
- No hard-rule violations in the current diff.

When both hold, commit right away:
- Use Conventional Commits: `feat(<area>): ...`, `fix(<area>): ...`, `chore: ...`, `docs: ...`.
- Stage only the files touched in the current loop. Never `git add -A` or `git add .` — protects against accidentally committing secrets or junk.
- Always add the trailer `Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`.
- Never push. Pushing is always the user's explicit call.
- Never amend. If a commit is wrong, create a follow-up commit.
- Never use `--no-verify`.

If the state is NOT stable, do not commit. Report what blocks stability and leave the working tree as-is.

## Commands

All day-to-day commands are wrapped in the `Makefile` — run `make help` for the full list. Quick reference:

```bash
make install   # create venv + `pip install -e '.[dev]'`
make test      # pytest -q
make serve     # uvicorn mad.api.app:create_app --factory (HOST=/PORT= override)
make clean     # drop caches, build artifacts, sessions/
```

The `mad` console script (`mad serve`) is also available once the package is installed.

## Key files

- `docs/backlog.md` — improvements deferred past v0.1.
- `docs/sandbox-bwrap.md` — operator's guide for hardening the sandbox with bubblewrap.
- `pyproject.toml` — package metadata, dependencies, build backend, and the `mad` console script. Single source of truth for `pip install -e .`.
- `src/mad/api/app.py` — `create_app(store=...)` factory and router wiring.
- `src/mad/core/` — session log, workspace, security primitives (hard rules 2, 3, 6 enforced here).
- `src/mad/providers/` — `AgentLauncher` protocol, `get_launcher` factory, and implementations (`claude_cli`, `fake`).
- `tests/conftest.py` — shared fixtures, including `fake_launcher` (built on `FakeLauncher` from `mad.providers.fake`) and `bare_repo`. Unit tests live under `tests/unit/`, FR acceptance tests under `tests/test_acceptance.py`.

## AgentLauncher contract

All launcher code implements this interface:

```python
class AgentLauncher(Protocol):
    async def run(
        self,
        prompt: str,
        workspace: Path,
        emit: Callable[[str, dict | None], Coroutine[Any, Any, None]],
    ) -> None: ...
```

The launcher receives the prompt, the workspace path, and an `emit` callback. It spawns the external agent, streams stdout line-by-line as `agent.output` events, and emits `session.status_idle` (exit 0) or `session.error` (non-zero / timeout) on completion. Current implementations:
- `claude_cli` — spawns `claude --dangerously-skip-permissions -p "{prompt}"` with `cwd=workspace`. Configurable via `MAD_CLAUDE_CLI_BIN` and `MAD_CLAUDE_CLI_TIMEOUT_S`.
- `fake` — `FakeLauncher` test double that emits a pre-scripted sequence of events without spawning any process.

The protocol lives in `mad.providers.base`. The factory `mad.providers.factory.get_launcher(agent.provider)` dispatches by name and is monkey-patched to `FakeLauncher` (from `mad.providers.fake`) in tests.
