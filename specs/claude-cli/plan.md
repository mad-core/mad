# Implementation Plan — Mad claude-cli provider

## Stack

```
Python 3.11+ stdlib only:
  asyncio          (asyncio.create_subprocess_exec, asyncio.timeout)
  json             (payload serialisation, stream-json line parsing)
  os               (os.environ for MAD_CLAUDE_CLI_BIN / MAD_CLAUDE_CLI_TIMEOUT_S)
  shutil           (shutil.which for PATH resolution)
```

No new entries in `pyproject.toml` dependencies. No Anthropic SDK import in `mad.providers.claude_cli`.

## Implementation rules

1. **Replace the stub, keep the file.** Edit `src/mad/providers/claude_cli.py` in place. Remove the `NotImplementedError` body (lines 6–8). Keep the module-level docstring. Do not touch `src/mad/providers/base.py` — the `LLMProvider` Protocol, `ProviderResponse`, and `ToolUse` dataclasses are the contract; this implementation must satisfy them without modifying them.

2. **Private parser helper in the same module.** Add `_StreamJsonParser` as a private class inside `src/mad/providers/claude_cli.py`, not as a new sub-package. The parser's public interface is `feed(line: str) -> None` and `result() -> ProviderResponse`. Raise `ClaudeCLIError` from `feed()` if a line is not valid JSON (defensive; should not happen with a well-behaved CLI).

3. **Factory needs no change (verify only).** `src/mad/providers/factory.py` already dispatches on `"claude_cli"` by name. After the stub is replaced the dispatch will work. If the constructor of `ClaudeCLIProvider` gains any required arguments, the factory must be updated accordingly — but the design intentionally puts all config in env vars so the constructor stays `ClaudeCLIProvider()` with no required args.

4. **New tests under `tests/unit/providers/test_claude_cli.py`.** Cover AC-1 through AC-5 using fake subprocesses (either a tiny Python script written to `tmp_path` or `monkeypatch` of `asyncio.create_subprocess_exec`). Do not import the real `claude` binary. Do not set `ANTHROPIC_API_KEY`. Reuse `pytest.mark.asyncio` from the existing test suite.

5. **New fixture `claude_cli_with_fake_bin` in `tests/conftest.py`.** The fixture writes a minimal fake `claude` Python script to `tmp_path`, marks it executable, sets `MAD_CLAUDE_CLI_BIN` in the environment via `monkeypatch`, and yields a `ClaudeCLIProvider()` instance. The fake script emits a hard-coded stream-json transcript that includes one text block and one `tool_use` block. This fixture powers AC-6.

6. **Do not create `specs/claude-cli/api.md`.** The HTTP surface is unchanged. State this explicitly in `README.md` and in any PR description so reviewers know the omission is intentional and not an oversight.

## Out of scope

The following are explicitly deferred. See [`../../docs/backlog.md`](../../docs/backlog.md) for the backlog context.

- **Resumable CLI sessions (`claude --resume <id>`).** Each `complete()` call starts a fresh process. Resumable sessions require tracking a CLI session ID across turns and are a separate backlog item.
- **Automatic `claude login` flow from Mad.** The operator authenticates once on the host (`claude login`). Mad never calls `claude login`, stores credentials, or detects that the CLI is unauthenticated beyond raising `ClaudeCLIError` with the CLI's own error message.
- **Windows support.** The implementation uses POSIX subprocess semantics (`proc.kill()`, `stdin.close()`, signal handling). Windows is not a supported platform for this feature.
- **Concurrency limits across a single Pro account.** Claude Pro/Max accounts have rate limits. If multiple Mad sessions simultaneously call `ClaudeCLIProvider.complete()`, they will each spawn a `claude` process. Throttling, queue depth, and account-level rate limit handling are the operator's responsibility. The risk is documented here; mitigation is a future backlog item.
- **MCP server passthrough.** If the local `claude` CLI is configured with MCP servers in `~/.claude/`, those tools load automatically into the CLI session. Mad has no visibility into those tool schemas and cannot route their calls through the harness. MCP passthrough is a distinct feature.
