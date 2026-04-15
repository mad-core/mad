# Requirements — Mad claude-cli provider

## Goal

Make `agent.provider = "claude_cli"` a fully functional provider that uses the locally authenticated `claude` CLI (Claude Pro/Max subscription) instead of the Anthropic API. No `ANTHROPIC_API_KEY` is needed; the CLI's own login (`~/.claude/`) provides authentication.

## Functional requirements

### FR-1 — Subprocess invocation

`ClaudeCLIProvider.complete()` MUST spawn `claude --print --output-format stream-json --verbose` as an async subprocess, pass the system prompt + message history + tool schemas on stdin as a single JSON payload, and stream stdout line-by-line.

### FR-2 — Stream-json parsing

Each stdout line is one JSON object. The provider MUST aggregate `assistant` message deltas into `ProviderResponse.text`, collect every `tool_use` block into `ProviderResponse.tool_uses` (preserving `id`, `name`, `input`), and capture the final `stop_reason` from the terminal `message_stop` / `result` event. The parser MUST NOT use regex to extract structured data from text (see CLAUDE.md hard rule 1).

### FR-3 — Reuse of existing auth

The provider MUST NOT read, write, or manage any credential files. It relies on `~/.claude/` being pre-authenticated on the host. If the CLI is missing or unauthenticated, the provider MUST raise a typed `ClaudeCLIError` that the harness can log as a `session.error` event without leaking environment variables or tokens into the error message.

### FR-4 — Tool schema passthrough

The `tools` argument (already in the `LLMProvider` Protocol) is forwarded unchanged in the stdin payload so the CLI receives the same JSON schemas the SDK path would declare.

### FR-5 — Message history format

`messages` (list of dicts with `role` + `content` blocks, including `tool_result` blocks) MUST be forwarded as-is in the stdin payload. The provider does not transform `tool_result` blocks into text.

### FR-6 — Factory wiring

`mad.providers.factory.get_provider("claude_cli")` MUST return a working `ClaudeCLIProvider` instance and MUST NOT raise. The `NotImplementedError` stub currently at `src/mad/providers/claude_cli.py` lines 6–8 is removed.

### FR-7 — Configurable CLI path

The executable path defaults to `claude` resolved via `shutil.which` on `$PATH`. It can be overridden by setting the environment variable `MAD_CLAUDE_CLI_BIN` to an absolute path (useful for pinned installs such as `~/.claude/local/claude`).

### FR-8 — Timeout and cancellation

A per-call timeout applies to every `complete()` invocation. The default is 120 seconds; it can be overridden with the environment variable `MAD_CLAUDE_CLI_TIMEOUT_S`. When the timeout fires, the subprocess MUST be killed and a `ClaudeCLIError` MUST be raised. Cancelling the harness asyncio task that owns the `complete()` call MUST terminate the child process (no zombie processes).

### FR-9 — No stdout leakage of secrets

If the CLI emits anything that resembles an auth token or environment snapshot on stdout, the provider MUST NOT relay it into `ProviderResponse.text`. Only content blocks of type `assistant` are forwarded; all other event types are consumed internally by the parser and discarded from the response.

## Non-functional constraints

### NFR-1 — Test isolation

Tests MUST NOT spawn the real `claude` binary (CLAUDE.md hard rule 5). Two valid strategies:

1. Write a tiny fake Python script to `tmp_path`, `chmod +x` it, and point `MAD_CLAUDE_CLI_BIN` at it. The script emits a canned stream-json transcript on stdout then exits 0.
2. Monkeypatch `asyncio.create_subprocess_exec` inside `mad.providers.claude_cli` to return a stub object with a pre-filled `stdout` async reader and a controlled `returncode`.

New unit tests live under `tests/unit/providers/test_claude_cli.py`. The existing `fake_provider` fixture continues to cover harness-level tests; a new sibling fixture `claude_cli_with_fake_bin` in `tests/conftest.py` sets up strategy 1 for the acceptance-level test (AC-6).

### NFR-2 — No new runtime dependencies

The implementation uses only Python 3.11+ stdlib: `asyncio.subprocess`, `json`, `os`, `shutil.which`. No `pexpect`, no Anthropic SDK import in this module.

### NFR-3 — Hard rules observed

Two CLAUDE.md hard rules apply directly to this feature and are restated here for the implementer:

- **Hard rule 1 — Native tool use only.** The stream-json parser MUST consume structured `tool_use` blocks from the CLI's JSON output. It MUST NOT extract tool calls by matching patterns in `ProviderResponse.text` or any other free-text field.
- **Hard rule 5 — Fake provider in tests.** Tests NEVER call the real `claude` CLI or the real Anthropic API. CI has no secrets. Any test that would require a live CLI is a hard failure.

## MVP acceptance criteria

The feature is done when all six criteria pass as `pytest` tests with no real network or CLI access.

### AC-1 — Correct ProviderResponse from a scripted subprocess

Unit test: call `ClaudeCLIProvider.complete()` with a fake subprocess (strategy 1 or 2) that emits one `assistant` text block followed by one `tool_use` block then a `message_stop` event. Assert that the returned `ProviderResponse` has the expected `text`, exactly one `ToolUse` whose `id`, `name`, and `input` match the scripted values, and `stop_reason == "tool_use"`.

### AC-2 — Factory returns a live ClaudeCLIProvider

Unit test: call `get_provider("claude_cli")` and assert the return value is an instance of `ClaudeCLIProvider` without raising.

### AC-3 — Non-zero exit raises ClaudeCLIError without leaking secrets

Unit test: fake subprocess exits with a non-zero code and writes a stderr message containing a mock token string. Assert that a `ClaudeCLIError` is raised, that `error.exit_code` matches the exit code, and that the mock token string does NOT appear in `str(error)` or `error.stderr_tail`.

### AC-4 — Cancellation terminates the subprocess

Unit test: start `complete()` with a fake subprocess that blocks indefinitely, then cancel the asyncio task after a short delay. Assert that the subprocess `.kill()` method was called (or that `returncode` is set to indicate termination) and that no zombie process is left.

### AC-5 — MAD_CLAUDE_CLI_BIN override is respected

Unit test: write a minimal fake `claude` binary to a custom path under `tmp_path`, set `MAD_CLAUDE_CLI_BIN` to that path, call `complete()`, and assert that the fake binary at the custom path was the one invoked (not any `claude` found on `$PATH`).

### AC-6 — End-to-end harness integration

Acceptance test: use `monkeypatch` to swap `factory.get_provider` so it returns a `ClaudeCLIProvider` instance backed by a `claude_cli_with_fake_bin` fixture. Run the agent loop for one step. Assert that `agent.message` and `agent.tool_use` events appear in the session log JSONL. This proves the provider plugs into `mad.agent` without any changes to the harness.
