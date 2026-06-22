"""Unit tests for ``resolve_effective_effort`` (issue #60).

Effort precedence is session > deployment only — narrower than
``resolve_effective_model`` (no task or machine level). Covers each level
plus the all-None fallback (negative twin).
"""

from __future__ import annotations

from mad.core.orchestration.domain.effort_config import resolve_effective_effort


def test_session_effort_wins_over_deployment_default() -> None:
    """A per-session effort overrides the deployment default."""
    result = resolve_effective_effort(
        session_effort="high",
        deployment_default="low",
    )
    assert result == "high"


def test_deployment_default_used_when_session_effort_none() -> None:
    """When session_effort is None, the deployment default is used."""
    result = resolve_effective_effort(
        session_effort=None,
        deployment_default="low",
    )
    assert result == "low"


def test_all_none_returns_none() -> None:
    """Negative twin: when both levels are unset, None is returned.

    None means: omit the effort flag and let the provider use its own default.
    """
    result = resolve_effective_effort(
        session_effort=None,
        deployment_default=None,
    )
    assert result is None


def test_session_effort_wins_even_when_deployment_default_none() -> None:
    """Session value is honoured regardless of an unset deployment default —
    the inverse of the deployment-fallback case above."""
    result = resolve_effective_effort(
        session_effort="medium",
        deployment_default=None,
    )
    assert result == "medium"
