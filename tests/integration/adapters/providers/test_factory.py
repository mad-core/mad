from __future__ import annotations

import pytest

from mad.adapters.outbound.agents.factory import get_launcher
from mad.adapters.outbound.agents.opencode import OpenCodeProvider
from mad.core.sessions.ports.outbound.agent_launcher import AgentLauncher


def test_get_launcher_unknown_name_raises():
    """Unknown / removed provider names must raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        get_launcher("anthropic_api")


def test_get_launcher_garbage_raises():
    with pytest.raises(NotImplementedError):
        get_launcher("does_not_exist")


def test_get_launcher_opencode_returns_agent_launcher():
    """get_launcher('opencode') must return an AgentLauncher-compatible instance."""
    launcher = get_launcher("opencode")
    assert isinstance(launcher, OpenCodeProvider)
    assert isinstance(launcher, AgentLauncher)
