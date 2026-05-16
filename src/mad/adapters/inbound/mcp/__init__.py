"""MCP inbound adapter.

Exposes Mad's existing session use cases as Model Context Protocol tools
over Streamable HTTP, mounted at ``/mcp`` on the public FastAPI app
(ADR-0010). Infrastructure-only: tools call use cases in-process and
return raw status — they never classify, interpret agent output, or
manage a conversation loop (hard rule 1).
"""

from .server import build_mcp_server

__all__ = ["build_mcp_server"]
