from __future__ import annotations

from mad.adapters.outbound.agents.claude_cli import ClaudeCLIProvider
from mad.adapters.outbound.agents.opencode import OpenCodeProvider
from mad.core.sessions.ports.outbound.agent_launcher import AgentLauncher


def get_launcher(name: str) -> AgentLauncher:
    if name == "claude_cli":
        return ClaudeCLIProvider()
    if name == "opencode":
        return OpenCodeProvider()
    raise NotImplementedError(f"Unknown launcher: {name!r}")
