"""Unit tests for the exponential-backoff retry schedule (issue #62)."""

from __future__ import annotations

import pytest

import mad.core.orchestration.domain.retry_schedule as sched


def test_backoff_doubles_each_attempt_up_to_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without jitter, each attempt doubles until the cap is reached."""
    monkeypatch.setattr(sched, "_JITTER_FRACTION", 0.0)
    monkeypatch.setattr(sched, "_MIN_BACKOFF_S", 0.0)

    assert sched.backoff_s(0) == pytest.approx(30.0)
    assert sched.backoff_s(1) == pytest.approx(60.0)
    assert sched.backoff_s(2) == pytest.approx(120.0)
    assert sched.backoff_s(3) == pytest.approx(240.0)
    assert sched.backoff_s(7) == pytest.approx(3600.0)  # capped
    assert sched.backoff_s(10) == pytest.approx(3600.0)  # still capped


def test_backoff_minimum_is_positive(monkeypatch) -> None:
    """backoff_s always returns a positive number, even with maximum negative jitter."""
    monkeypatch.setattr(sched, "_JITTER_FRACTION", 1.0)
    import random

    monkeypatch.setattr(random, "random", lambda: 0.0)  # maximum negative jitter
    result = sched.backoff_s(0)
    assert result >= 1.0


def test_backoff_returns_float(monkeypatch) -> None:
    monkeypatch.setattr(sched, "_JITTER_FRACTION", 0.0)
    result = sched.backoff_s(0)
    assert isinstance(result, float)
    assert result == pytest.approx(sched._BASE_S)


def test_exceeds_ceiling_false_below_threshold() -> None:
    assert not sched.exceeds_ceiling(sched.CUMULATIVE_CEILING_S - 1.0)


def test_exceeds_ceiling_true_at_threshold() -> None:
    assert sched.exceeds_ceiling(sched.CUMULATIVE_CEILING_S)


def test_exceeds_ceiling_true_above_threshold() -> None:
    assert sched.exceeds_ceiling(sched.CUMULATIVE_CEILING_S + 100.0)


def test_ceiling_is_five_hours() -> None:
    assert sched.CUMULATIVE_CEILING_S == 5 * 3600.0
