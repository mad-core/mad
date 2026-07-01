---
service: mad
domain: backend
section: user-manuals
source_of_truth: repo
---

# Connect Claude Code or Any MCP Client to Mad

## What this lets you do

Everything in this section is also available as a set of tools an AI agent
can call directly. Point Claude Code (or any MCP-speaking client) at Mad's
`/mcp` endpoint and it gets the same session, event, queue, workflow, and
model tools shown throughout these manuals — no hand-written HTTP calls
required.

## Before you start

- Mad already running and reachable — locally, or through a tunnel.
- An MCP-capable client (Claude Code is used below; any client that speaks
  Streamable HTTP MCP works the same way).
- If you reach Mad through a tunnel with an access gate, you'll need
  whatever headers or tokens that gate requires — one-time client setup,
  separate from Mad itself.

## Step by step

### Step 1 — Point your client at `/mcp`

Mad exposes its whole tool surface at one path, on the same address as its
HTTP API — no separate port, no separate process.

#### Using the HTTP API

There's no HTTP call for this step — it's client-side configuration. If you
want to sanity-check the endpoint directly first:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' \
  -H 'Accept: application/json, text/event-stream' -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}' \
  http://127.0.0.1:8000/mcp
```

Expect `200`.

#### Using MCP tools

Register Mad as an MCP server with Claude Code:

```bash
claude mcp add --transport http mad http://127.0.0.1:8000/mcp
```

For a tunneled/remote Mad, and the exact headers an access-gated tunnel
needs, see [`runbooks/claude-code-mcp.md`](../05-operations/runbooks/claude-code-mcp.md) —
this page covers the local case; that one covers the operator-side gate
setup.

### Step 2 — See what shows up

Once connected, your client can list Mad's tools (in Claude Code, ask it, or
check its MCP status). You'll see one tool per capability covered in this
section: creating and messaging sessions, querying events, queueing and
scheduling tasks, running workflows, and choosing agent/model/effort.

### Step 3 — Use it exactly like the HTTP examples in this section

Everything you can do over HTTP in these manuals, you can do as a tool call
with the same fields — ask your client in natural language and it picks the
right tool, or call one directly:

```
mad_create_session({
  "payload": {"agent": {"name": "my-agent", "provider": "claude_cli"}, "resources": []}
})
```

is the tool-call equivalent of `POST /v1/sessions` from
[`getting-started.md`](getting-started.md) and [`sessions.md`](sessions.md).

## What you get back

The same response shapes as HTTP, just handed to your client instead of
printed by curl — `mad_create_session` returns the identical `session_id` /
`status` / `workspace` fields as `POST /v1/sessions`.

## Under the hood

`/mcp` is a second door into the same building as the HTTP door — same
rooms, same staff, just a different way to knock. Nothing behind it works
differently because you came in through MCP; Mad is still the front desk
handing work to the same agents, never doing the work itself.

## Common problems

| Symptom | Likely cause | Fix |
|---|---|---|
| `404` on `/mcp` | An old Mad build without the MCP mount, or a typo in the path | Update Mad; confirm the path is exactly `/mcp` |
| `421` / "Invalid Host header" | Host-header protection is on and doesn't recognize your hostname | See [`runbooks/claude-code-mcp.md`](../05-operations/runbooks/claude-code-mcp.md) for the allowlist setting |
| A tool call fails for a session id you know exists | The id is wrong, or you're looking at a stale list | Call `mad_list_sessions` to get the authoritative current ids |
| A tool you expected isn't there | The live event stream deliberately has no tool (see [`events.md`](events.md)) — everything else should be present | Check [`../01-overview/operations.md`](../01-overview/operations.md) for the authoritative catalog if something else seems missing |

## See also

- [`getting-started.md`](getting-started.md) — the same first round trip,
  shown for both surfaces.
- [`events.md`](events.md) — why the live stream specifically has no MCP
  tool.
