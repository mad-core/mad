# ADR-0010 — MCP exposed as an HTTP-mounted inbound adapter

- Status: Accepted
- Date: 2026-05-15

## Context

Driving Mad today means writing HTTP client glue per adopter. Issue #32 wants an operator to drive Mad **from an AI agent** (Claude Code / Claude Desktop on a laptop): *launch work* and then *ask in natural language* — "which sessions failed? which can I delete?". The Model Context Protocol (MCP) is the interface those agents already speak.

Three forces shaped the design:

1. **The orchestrator is remote; Mad is self-hosted.** The agent runs on a laptop, Mad runs on the operator's machine reachable only through the Cloudflare Tunnel that already proxies the REST API (ADR-0006, `docs/05-operations/runbooks/cloudflare-tunnel.md`). The MCP transport has to ride that same tunnel.
2. **Mad must keep inferring nothing (hard rule 1, ADR-0004).** "Failed", "needs attention", "safe to delete" are the orchestrator LLM's conclusions. Mad exposes use cases and returns raw `status`.
3. **No schema may drift from the REST boundary (hard rule 9).** A second hand-written model set for MCP would diverge from the HTTP request/response models the moment either side changes.

The original issue floated stdio transport. stdio has no port and cannot be tunneled, so it cannot satisfy the laptop→remote-Mad topology that motivates the feature.

## Decision

### 1. MCP is a Streamable-HTTP ASGI app mounted at `/mcp` on the public FastAPI app

`build_mcp_server(...)` (in `src/mad/adapters/inbound/mcp/`) constructs a `FastMCP` (official `mcp` SDK, `mcp>=1.0,<2`) with `streamable_http_path="/"`, and `create_app` mounts its `streamable_http_app()` at `/mcp`. No third port, no third process: `mad serve`'s existing public uvicorn serves it. The StreamableHTTP session manager is entered inside the existing app lifespan, alongside the dispatcher.

The MCP adapter is a **peer inbound adapter** on the hexagon (ADR-0003), not a layer stacked on top of HTTP.

### 2. Tools call use cases in-process, not Mad's own HTTP routes

Each of the five tools instantiates the same use case the corresponding REST handler instantiates, against the same injected dependencies (`store` / `session_repo` / `workspace_provisioner` / `launcher_factory` / `event_emitter` / `task_projection`) read from `app.state`. Writes still flow through `EventEmitter` (hard rule 11). No MCP→HTTP self-call.

### 3. Five tools, ~1:1 with the session use cases — no event tools

> **Superseded by [ADR-0012](0012-http-mcp-tool-parity.md) (2026-06-12).** The five-tool curated subset proved too narrow: orchestration and the bounded event query were reachable over HTTP but not MCP, and MCP is the primary consumer. ADR-0012 establishes full parity — every request/response `/v1` route is a tool — with the streaming SSE surface (`GET /v1/events/stream`) as the sole carve-out. The decision below is retained for history.

`mad_create_session`, `mad_send_message`, `mad_list_sessions`, `mad_get_session`, `mad_delete_session`. `agent.*` output, hooks, and the cross-session event stream are deliberately **not** tools — they are operator telemetry on the existing SSE surface (ADR-0004), a non-actionable firehose for an orchestrator.

### 4. Tool schemas reuse the HTTP layer's Pydantic models

Tool inputs/outputs are typed with the *same* `CreateSessionRequest` / `SendMessageRequest` / `SessionSummaryResponse` / `SessionDetailResponse` classes the HTTP routes use. The MCP schema cannot drift from OpenAPI because it is generated from the same classes; a CI contract test (`tests/integration/api/test_mcp_http.py`) asserts structural equality across the `$defs` ↔ `components/schemas` ref dialects.

### 5. Authentication stays at the Cloudflare edge; DNS-rebinding protection is off by default

No auth code enters Mad. The security boundary is Cloudflare Access (Service Token) plus the loopback bind — identical to the REST API (ADR-0006, `docs/05-operations/runbooks/cloudflare-tunnel.md`). MCP's built-in DNS-rebinding protection defaults to ON with an empty host allowlist, which would reject the tunnel hostname and break the deployment entirely. It is therefore **disabled by default**; operators wanting in-process defense-in-depth set `MAD_MCP_ALLOWED_HOSTS` (comma-separated) to flip it on, scoped to those hosts. DNS-rebinding protection guards browser-driven *local* servers — not the control plane for a token-gated tunnel.

## Consequences

**Wins:**

- An MCP client configured against `https://mad.example.com/mcp` with the existing `CF-Access-Client-Id/Secret` headers reaches Mad with zero new ingress rules and zero Mad-side auth.
- The MCP and REST boundaries cannot diverge: one model set, enforced by a contract test.
- Mad still infers nothing — the tool surface is thin and the classification stays with the caller.

**Costs:**

- The app lifespan now also runs the StreamableHTTP session manager. Tests that need the transport (not just tool behaviour) must run with the lifespan active (`with TestClient(...)`).
- `src/mad/adapters/inbound/http/app.py` imports the MCP adapter lazily inside `create_app` to break the import cycle created by reusing the HTTP route models.
- Disabling DNS-rebinding protection by default is a deliberate, documented trade-off; it is safe only because the tunnel + Access posture is mandatory for any non-loopback exposure.

**Revisit if:**

- Multi-tenancy lands (ADR-0006): per-caller event isolation and per-tenant MCP semantics become necessary.
- OAuth 2.1 / dynamic client registration is adopted (Phase 2): the edge-auth assumption changes and `auth_server_provider` wiring enters the adapter.

## Alternatives considered

- **stdio transport.** Rejected: no port, cannot be tunneled, cannot satisfy the laptop→remote-Mad requirement that motivates the feature.
- **A separate MCP process/port.** Rejected: a third bind to firewall and tunnel for no benefit; co-location reuses the existing uvicorn and the existing Access policy.
- **MCP tools call Mad's own HTTP routes.** Rejected: stacks MCP→HTTP, double-serializes, and would route writes around `EventEmitter`. In-process use-case calls keep adapters as hexagon peers (ADR-0003) and preserve hard rule 11.
- **A bespoke MCP model set.** Rejected: guarantees drift from OpenAPI. Reusing the HTTP Pydantic models makes drift structurally impossible and testable.
- **Event/hook tools (`tail_events`, `query_events`).** Rejected: a non-actionable firehose for an orchestrator and an LLM-disambiguation cost. Telemetry stays on SSE (ADR-0004).
- **Keep MCP's default DNS-rebinding protection.** Rejected: with an empty allowlist it rejects every Host header including the tunnel hostname, breaking the deployment. The real control is Cloudflare Access; an in-Mad host allowlist contradicts the edge-auth posture and is offered only as opt-in.

## Cross-references

- [ADR-0003](0003-package-layout.md) — hexagonal layout; MCP is an inbound adapter peer, not a layer on HTTP.
- [ADR-0004](0004-events-module-vocabulary-and-scope.md) — events are observability only; this ADR's "no event tools" follows directly.
- [ADR-0006](0006-multi-tenancy-deferred.md) — single-operator assumption; Cloudflare Access covers auth.
- [ADR-0007](0007-single-write-gateway-event-emitter.md) — tools call use cases, which write via `EventEmitter`; the adapter never writes directly.
- `docs/05-operations/runbooks/cloudflare-tunnel.md` / `docs/05-operations/runbooks/claude-code-mcp.md` — operator exposure and client-config guides.
