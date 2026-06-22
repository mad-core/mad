"""Unit tests for the agent-agnostic timeout resolver (issue #61).

Precedence is session > env > 600 s default. Unlike model/effort there is
no "omit" sentinel — every run gets a concrete float. Covers each level
plus the all-None fallback (negative twin) and the env-reader's malformed
/ unset handling.
"""

from __future__ import annotations

import pytest

from mad.core.orchestration.domain.timeout_config import (
    AGENT_TIMEOUT_ENV_VAR,
    DEFAULT_AGENT_TIMEOUT_S,
    env_timeout_s,
    resolve_effective_timeout,
)


def test_session_timeout_wins_over_env() -> None:
    """A per-session timeout overrides the operator env default."""
    result = resolve_effective_timeout(session_timeout_s=30.0, env_timeout_s=900.0)
    assert result == 30.0


def test_env_used_when_session_timeout_none() -> None:
    """When session_timeout_s is None, the env default is used."""
    result = resolve_effective_timeout(session_timeout_s=None, env_timeout_s=900.0)
    assert result == 900.0


def test_all_none_returns_hardcoded_default() -> None:
    """Negative twin: when both levels are unset, the 600 s default is returned.

    There is no None sentinel — every launch has a concrete budget.
    """
    result = resolve_effective_timeout(session_timeout_s=None, env_timeout_s=None)
    assert result == DEFAULT_AGENT_TIMEOUT_S
    assert result == 600.0


def test_session_timeout_wins_even_when_env_none() -> None:
    """Session value is honoured regardless of an unset env default —
    the inverse of the env-fallback case above."""
    result = resolve_effective_timeout(session_timeout_s=45.0, env_timeout_s=None)
    assert result == 45.0


# ---------------------------------------------------------------------------
# env_timeout_s() reader
# ---------------------------------------------------------------------------


def test_env_timeout_s_reads_numeric_value(monkeypatch: pytest.MonkeyPatch) -> None:
    """A numeric MAD_AGENT_TIMEOUT_S is parsed to a float."""
    monkeypatch.setenv(AGENT_TIMEOUT_ENV_VAR, "120")
    assert env_timeout_s() == 120.0


def test_env_timeout_s_none_when_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative twin: an unset env var yields None so the resolver falls back."""
    monkeypatch.delenv(AGENT_TIMEOUT_ENV_VAR, raising=False)
    assert env_timeout_s() is None


def test_env_timeout_s_none_when_malformed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-numeric value yields None rather than crashing a launch."""
    monkeypatch.setenv(AGENT_TIMEOUT_ENV_VAR, "not-a-number")
    assert env_timeout_s() is None
