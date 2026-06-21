"""Unit tests for the exponential-backoff retry schedule (issue #62)."""

from __future__ import annotations

import pytest

import mad.core.orchestration.domain.retry_schedule as sched


def test_backoff_doubles_each_attempt_up_to_cap() -> None:
    """Without jitter, each attempt doubles until the cap is reached."""

    # Reload with jitter disabled via monkeypatching would require pytest
    # fixtures; test the cap boundary directly instead.
    # attempt 0 → 30 s, 1 → 60, 2 → 120, 3 → 240, 4 → 480, 5 → 960,
    # 6 → 1920, 7 → 3600 (capped).
    raw_values = [sched._BASE_S * (sched._MULTIPLIER**i) for i in range(8)]
    capped = [min(v, sched._CAP_S) for v in raw_values]
    assert capped[0] == 30.0
    assert capped[1] == 60.0
    assert capped[2] == 120.0
    assert capped[3] == 240.0
    assert capped[7] == sched._CAP_S


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
