"""Exponential-backoff schedule for the rate-limit retry loop (issue #62).

Constants and helpers are pure functions — no I/O, no asyncio.  The
dispatcher imports them to drive the retry loop without coupling to
the concrete timer implementation.

Schedule parameters (v1 — issue scope says these are fixed; a
follow-up issue will make them configurable per ADR):

- Base interval: 30 s
- Multiplier: 2 (doubles each attempt)
- Per-interval cap: 3 600 s (1 h)
- Cumulative ceiling: 18 000 s (5 h) — after which the task is failed
  with ``reason: "rate_limit_exhausted"``

Jitter: ±10 % to avoid thundering-herd when multiple sessions hit the
ceiling at the same time.  The dispatcher calls ``backoff_s(attempt)``
and passes the result to ``asyncio.sleep``; the result already contains
jitter.
"""

from __future__ import annotations

import random

CUMULATIVE_CEILING_S: float = 5 * 3600.0  # 18 000 s
_BASE_S: float = 30.0
_MULTIPLIER: float = 2.0
_CAP_S: float = 3600.0  # 1 h per interval
_JITTER_FRACTION: float = 0.10
_MIN_BACKOFF_S: float = 1.0  # never sleep less than 1 s in production


def backoff_s(attempt: int) -> float:
    """Return the sleep duration for the given retry attempt (0-based).

    ``attempt=0`` is the first retry (after the initial failure).
    The raw interval is ``BASE * MULTIPLIER ** attempt``, capped at
    ``CAP_S``, then jittered by ±JITTER_FRACTION, with a floor of
    ``_MIN_BACKOFF_S`` (monkeypatch-able in tests).
    """
    raw = _BASE_S * (_MULTIPLIER**attempt)
    capped = min(raw, _CAP_S)
    jitter = capped * _JITTER_FRACTION * (2 * random.random() - 1)  # noqa: S311
    return max(_MIN_BACKOFF_S, capped + jitter)


def exceeds_ceiling(cumulative_s: float) -> bool:
    """Return True when accumulated wait time has reached the 5 h ceiling."""
    return cumulative_s >= CUMULATIVE_CEILING_S
