"""Agent-agnostic launcher timeout + precedence resolver (issue #61).

Replaces the two provider-specific timeout env vars
(``MAD_CLAUDE_CLI_TIMEOUT_S`` / ``MAD_OPENCODE_TIMEOUT_S``) with a single
operator knob, ``MAD_AGENT_TIMEOUT_S``, plus an optional per-session
override threaded from ``CreateSessionRequest.timeout_s``.

Mirrors the ``resolve_effective_model`` precedence helper (issue #55):
a pure function that takes every level as an explicit argument so it stays
framework-free and trivially testable.  Unlike model/effort there is no
deployment-config singleton — the operator default lives in the
``MAD_AGENT_TIMEOUT_S`` env var, read at the use-case boundary and passed
in here as ``env_timeout_s``.

Precedence (most specific wins):

1. per-session ``timeout_s`` (from the request)
2. ``MAD_AGENT_TIMEOUT_S`` env var (operator default)
3. hard-coded default: 600 s
"""

from __future__ import annotations

import os

#: Hard-coded fallback when neither a per-session override nor the
#: ``MAD_AGENT_TIMEOUT_S`` env var is set.
DEFAULT_AGENT_TIMEOUT_S = 600.0

#: Operator-facing env var that sets the global launcher timeout default.
AGENT_TIMEOUT_ENV_VAR = "MAD_AGENT_TIMEOUT_S"


def resolve_effective_timeout(
    session_timeout_s: float | None,
    env_timeout_s: float | None,
    default_timeout_s: float = DEFAULT_AGENT_TIMEOUT_S,
) -> float:
    """Precedence: session > env > default.

    Returns the first non-None value, falling back to ``default_timeout_s``
    (600 s) when both the per-session override and the operator env default
    are unset.  Always returns a concrete float — every launcher run has a
    timeout, there is no "omit" sentinel (unlike model/effort).
    """
    for candidate in (session_timeout_s, env_timeout_s):
        if candidate is not None:
            return candidate
    return default_timeout_s


def env_timeout_s() -> float | None:
    """Read ``MAD_AGENT_TIMEOUT_S`` from the environment.

    Returns the parsed float, or ``None`` when the var is unset or empty so
    the resolver falls back to its hard-coded default.  A malformed value
    (non-numeric) also yields ``None`` rather than crashing a launch — the
    operator default silently reverts to 600 s.
    """
    raw = os.environ.get(AGENT_TIMEOUT_ENV_VAR)
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None
