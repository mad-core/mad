# Driving Mad from an AI agent over MCP

Mad exposes its session use cases as [Model Context Protocol](https://modelcontextprotocol.io) tools, so you can drive it from Claude Code / Claude Desktop instead of hand-writing HTTP calls: *launch work*, then *ask in natural language* — "which sessions failed? which can I delete?".

The decision record behind this is [ADR-0010](adr/0010-mcp-mounted-http-inbound-adapter.md). Read it if you want the *why*; this guide is the *how*.

## What `mad serve` exposes

`mad serve` (and `make serve`) mounts the MCP server as a Streamable-HTTP ASGI app at **`/mcp`** on the same public FastAPI app that serves `/v1/*`. No extra port, no extra process — the existing uvicorn serves it.

Five tools, ~1:1 with the REST surface:

| Tool | Does | Returns |
|---|---|---|
| `mad_create_session` | provision a workspace + mount resources | session id, status, workspace path |
| `mad_send_message` | launch work in a session | `{"status": "accepted"}` immediately — does **not** wait for the agent |
| `mad_list_sessions` | every session + raw `status` | `running` / `idle` / `error` / `created` / `deleted` |
| `mad_get_session` | detail of one session | status, workspace, full event log |
| `mad_delete_session` | destroy a session's workspace | `{"status": "deleted", ...}` |

There are **no event or hook tools**. Per-line `agent.output`, `agent.*.hook.*`, and the cross-session stream are operator telemetry on `GET /v1/events/stream` — a non-actionable firehose for an orchestrator (ADR-0004). The "which failed / needs attention / safe to delete" reasoning is the orchestrator LLM's job over `mad_list_sessions` output; Mad returns raw `status` and infers nothing.

## Local use (same machine)

Point your MCP client at the loopback endpoint:

```
http://127.0.0.1:8000/mcp
```

Claude Code:

```bash
claude mcp add --transport http mad http://127.0.0.1:8000/mcp
```

## Remote use through the Cloudflare Tunnel

This is the topology the feature exists for: the agent on your laptop, Mad self-hosted, reached through the **same tunnel and the same Cloudflare Access Service Token** that already protect the REST API. Set the tunnel up first — see [`docs/cloudflare-tunnel.md`](cloudflare-tunnel.md). No new ingress rule and **no Mad-side auth** is involved: the endpoint `https://mad.example.com/mcp` rides the existing `mad.example.com → 127.0.0.1:8000` ingress, and Cloudflare Access rejects any request without a valid Service Token before it reaches Mad.

Claude Desktop / Claude Code remote-MCP config — pass the two Access headers through:

```json
{
  "mcpServers": {
    "mad": {
      "type": "http",
      "url": "https://mad.example.com/mcp",
      "headers": {
        "CF-Access-Client-Id": "<client-id>.access",
        "CF-Access-Client-Secret": "<client-secret>"
      }
    }
  }
}
```

Claude Code CLI equivalent:

```bash
claude mcp add --transport http mad https://mad.example.com/mcp \
  --header "CF-Access-Client-Id: ${CF_ACCESS_CLIENT_ID}" \
  --header "CF-Access-Client-Secret: ${CF_ACCESS_CLIENT_SECRET}"
```

(The same `~/.config/mad/cf-tunnel.env` you created in the tunnel guide carries these.)

## Host header / DNS-rebinding protection

The `mcp` SDK ships DNS-rebinding protection that, with its default empty allowlist, rejects **every** `Host` header — including your tunnel hostname. That protection is meant for browser-reachable *local* servers; it is not the control plane for a token-gated tunnel, where Cloudflare Access is the boundary. Mad therefore **disables it by default**.

If you want in-process defense-in-depth anyway, set:

```bash
export MAD_MCP_ALLOWED_HOSTS="mad.example.com"   # comma-separated for several
```

When set, protection is enabled and scoped to exactly those hosts. Leave it unset for the standard tunnel deployment.

## Manual validation (run these once after setup)

1. **Endpoint is mounted (local):**

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H 'Accept: application/json, text/event-stream' \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}' \
     http://127.0.0.1:8000/mcp
   ```

   Expect `200`. A `404` means the mount is missing; a `421` means DNS-rebinding protection is rejecting the Host header (see above).

2. **Reachable through the tunnel WITH a Service Token:**

   ```bash
   curl -sS -o /dev/null -w '%{http_code}\n' \
     -H "CF-Access-Client-Id: $CF_ACCESS_CLIENT_ID" \
     -H "CF-Access-Client-Secret: $CF_ACCESS_CLIENT_SECRET" \
     -H 'Accept: application/json, text/event-stream' \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}' \
     "$MAD_BASE_URL/mcp"
   ```

   Expect `200`.

3. **Rejected through the tunnel WITHOUT a Service Token** (this is the security assertion):

   ```bash
   curl -sS "$MAD_BASE_URL/mcp" | head -c 200
   ```

   Expect the Cloudflare Access **HTML login page**, never a JSON-RPC body. If you see JSON, the Access policy is not attached — stop and fix it before continuing (see the threat model in `docs/cloudflare-tunnel.md`).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `404` on `/mcp` locally | Running an old build without the mount | `make install` and restart `mad serve` |
| `421 Misdirected Request` / "Invalid Host header" | DNS-rebinding protection rejecting the Host | Unset `MAD_MCP_ALLOWED_HOSTS`, or add the hostname to it |
| `307` then success | `/mcp` → `/mcp/` redirect (normal Starlette mount behaviour) | None — MCP clients follow it automatically |
| HTML login page from the tunnel | Service Token missing or not in the Access policy | Attach the token to the `mad-service-clients` policy (tunnel guide §3–4) |
| `502 Bad Gateway` from the tunnel | Mad not listening on `127.0.0.1:8000` | Restart the `mad` supervisor unit |
| Tool call returns an error result for a known session id | Session only on disk and not yet rehydrated, or wrong id | Call `mad_list_sessions` to get the authoritative id list |

## Scope notes

- OAuth 2.1 / dynamic client registration is Phase 2; Cloudflare Access covers the single-operator case (ADR-0006).
- Convenience tools (create+send in one call) and task-queue tools are explicitly out of v0 — validate the five primitives first.
- MCP resources and `notifications/progress` are deferred (Phase 2).
