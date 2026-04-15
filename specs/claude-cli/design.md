# Design — Mad claude-cli provider

## Overview

`ClaudeCLIProvider` is a thin async wrapper around the `claude` CLI subprocess. It translates the `LLMProvider.complete()` call into a subprocess invocation, feeds the conversation context on stdin, streams the structured JSON response from stdout, and maps it into the shared `ProviderResponse` type. No network calls, no SDK, no credential management — the CLI handles all of that.

```
mad.agent (harness)
        │
        │  complete(system, messages, tools)
        ▼
ClaudeCLIProvider
        │
        │  asyncio.create_subprocess_exec("claude", "--print",
        │      "--output-format", "stream-json", "--verbose",
        │      stdin=PIPE, stdout=PIPE, stderr=PIPE)
        │
        │  stdin ◄── JSON payload (one blob, then EOF)
        │
        │  stdout ──► _StreamJsonParser (line-by-line)
        │
        ▼
ProviderResponse(text, tool_uses, stop_reason)
        │
        ▼
mad.agent (harness continues)
```

## Stdin payload shape

The provider writes exactly one JSON object to stdin, then closes the pipe (EOF signals end of input to the CLI):

```json
{
  "system": "<system prompt string>",
  "messages": [
    {"role": "user", "content": [{"type": "text", "text": "..."}]},
    {"role": "assistant", "content": [
      {"type": "tool_use", "id": "tu_1", "name": "bash", "input": {"cmd": "ls"}}
    ]},
    {"role": "user", "content": [
      {"type": "tool_result", "tool_use_id": "tu_1", "content": "file_a\nfile_b"}
    ]}
  ],
  "tools": [
    {
      "name": "bash",
      "description": "Run a shell command",
      "input_schema": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}
    }
  ]
}
```

The `messages` and `tools` lists are forwarded verbatim from the `complete()` arguments — no transformation, no encoding of `tool_result` blocks into text.

## Stream-json parser state machine

The CLI emits one JSON object per stdout line. `_StreamJsonParser` reads lines and transitions through these states:

```
IDLE
  │
  │  line: {"type": "message_start", ...}
  ▼
IN_MESSAGE
  │
  ├── line: {"type": "content_block_start", "content_block": {"type": "text"}}
  │     ▼  ACCUMULATING_TEXT
  │     │  line: {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "..."}}
  │     │    → append delta.text to current_text_buffer
  │     │  line: {"type": "content_block_stop"}
  │     │    → flush current_text_buffer into response.text
  │     ▼  back to IN_MESSAGE
  │
  ├── line: {"type": "content_block_start", "content_block": {"type": "tool_use", "id": ..., "name": ...}}
  │     ▼  ACCUMULATING_TOOL_USE
  │     │  line: {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "..."}}
  │     │    → append partial_json to current_tool_json_buffer
  │     │  line: {"type": "content_block_stop"}
  │     │    → json.loads(current_tool_json_buffer) → ToolUse(id, name, input)
  │     │    → append to response.tool_uses
  │     ▼  back to IN_MESSAGE
  │
  └── line: {"type": "message_delta", "delta": {"stop_reason": "..."}}
  │     → capture stop_reason
  │
  └── line: {"type": "message_stop"}  (or {"type": "result"})
        ▼
      DONE  → return ProviderResponse
```

Lines with unknown `type` values are silently skipped. Only `assistant`-role content blocks contribute to `ProviderResponse.text` or `ProviderResponse.tool_uses`. Auth-related or diagnostic events from `--verbose` are consumed and discarded.

## Subprocess lifecycle

```
1. Resolve the executable:
   - Read MAD_CLAUDE_CLI_BIN from env; fall back to shutil.which("claude").
   - If neither resolves, raise ClaudeCLIError(exit_code=None, stderr_tail="claude not found on PATH").

2. Spawn:
   proc = await asyncio.create_subprocess_exec(
       executable, "--print", "--output-format", "stream-json", "--verbose",
       stdin=asyncio.subprocess.PIPE,
       stdout=asyncio.subprocess.PIPE,
       stderr=asyncio.subprocess.PIPE,
   )

3. Write stdin:
   payload = json.dumps({"system": system, "messages": messages, "tools": tools})
   proc.stdin.write(payload.encode())
   await proc.stdin.drain()
   proc.stdin.close()

4. Stream stdout with timeout:
   async with asyncio.timeout(timeout_seconds):
       async for line in proc.stdout:
           parser.feed(line.decode())

5. Wait for exit:
   await proc.wait()

6. Map exit code:
   - exit code 0  → return parser.result()
   - exit code != 0 → read stderr tail (last 2 KB), scrub token patterns,
                       raise ClaudeCLIError(exit_code, stderr_tail)

7. On asyncio.CancelledError or asyncio.TimeoutError:
   proc.kill()
   await proc.wait()
   raise  (re-raise the original exception so the harness can record session.error)
```

## ClaudeCLIError taxonomy

`ClaudeCLIError` is defined in `mad.providers.claude_cli` (not in `base.py`):

```python
class ClaudeCLIError(RuntimeError):
    def __init__(self, exit_code: int | None, stderr_tail: str) -> None:
        self.exit_code = exit_code
        self.stderr_tail = stderr_tail  # last 2 KB of stderr, token patterns scrubbed
        super().__init__(f"claude CLI failed (exit={exit_code}): {stderr_tail}")
```

Subtypes by cause:

| Cause | exit_code | stderr_tail content |
|---|---|---|
| Binary not found | `None` | `"claude not found on PATH"` |
| Auth failure (not logged in) | non-zero | CLI's auth error message (scrubbed) |
| Timeout | `None` | `"timed out after {N}s"` |
| Non-zero exit (other) | non-zero | Last 2 KB of stderr (scrubbed) |

Scrubbing removes strings that match the pattern of Anthropic API keys (`sk-ant-...`) and any value from environment variables whose names contain `TOKEN`, `KEY`, or `SECRET`. Scrubbing replaces matched spans with `[REDACTED]`.

## Explicit non-goals

The following design choices are intentional and out of scope for this implementation:

- **No `--resume` flag.** Each `complete()` call is a fresh subprocess invocation. The session ID and turn management live in `mad.core`, not in the CLI process. Resumable CLI sessions are deferred — see `docs/backlog.md`.
- **No session ID juggling.** The provider does not track `--session-id` across calls. Statefulness is provided by the `messages` history that the harness accumulates.
- **No interactive mode.** The subprocess reads stdin, produces stdout, and exits. There is no persistent interactive process shared across turns.
- **No MCP passthrough.** Any MCP server configuration in `~/.claude/` that the CLI picks up by default is not managed by Mad. If the CLI loads MCP tools automatically, those tool schemas are not surfaced to the harness and their calls will be unresolvable.
