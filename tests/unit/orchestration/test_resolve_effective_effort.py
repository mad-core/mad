"""Unit tests for ``resolve_effective_effort`` (issues #60, #81).

Effort precedence is task > session > deployment (issue #81) — symmetric
with ``resolve_effective_model`` minus the machine level. Covers each level
plus the all-None fallback (negative twin).
"""

from __future__ import annotations

from mad.core.orchestration.domain.effort_config import resolve_effective_effort


def test_task_effort_wins_over_session_and_deployment() -> None:
    """A per-task effort overrides both the session and deployment levels."""
    result = resolve_effective_effort(
        task_effort="xhigh",
        session_effort="high",
        deployment_default="low",
    )
    assert result == "xhigh"


def test_session_effort_wins_when_no_task_effort() -> None:
    """When task_effort is None, the per-session effort is used."""
    result = resolve_effective_effort(
        task_effort=None,
        session_effort="high",
        deployment_default="low",
    )
    assert result == "high"


def test_deployment_default_used_when_no_task_or_session_effort() -> None:
    """When task_effort and session_effort are None, the deployment default is used."""
    result = resolve_effective_effort(
        task_effort=None,
        session_effort=None,
        deployment_default="low",
    )
    assert result == "low"


def test_all_none_returns_none() -> None:
    """Negative twin: when every level is unset, None is returned.

    None means: omit the effort flag and let the provider use its own default.
    """
    result = resolve_effective_effort(
        task_effort=None,
        session_effort=None,
        deployment_default=None,
    )
    assert result is None


def test_task_effort_wins_even_when_lower_levels_none() -> None:
    """Task value is honoured regardless of unset session/deployment levels —
    the inverse of the deployment-fallback case above."""
    result = resolve_effective_effort(
        task_effort="medium",
        session_effort=None,
        deployment_default=None,
    )
    assert result == "medium"
