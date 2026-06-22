"""Deployment-wide reasoning-effort configuration + precedence resolver (issue #60).

Mirrors the DeploymentModelConfig pattern (issue #55) exactly — effort is the
parallel knob to model: one mutable process-global singleton, persisted under a
reserved session log, bootstrapped at startup. ``None`` everywhere means "omit
the effort flag" (``--effort`` for claude, ``--variant`` for opencode) so the
provider uses its own default — Mad imposes no opinion and never enumerates or
validates effort values (opaque pass-through for v1).

Precedence is session > deployment only — there is no task-level effort
(out of scope, issue #60). This is deliberately narrower than
``resolve_effective_model``'s four levels.
"""

from __future__ import annotations

from dataclasses import dataclass

DEPLOYMENT_EFFORT_SESSION_ID = "__deployment_effort__"


@dataclass
class DeploymentEffortConfig:
    """Mutable process-global holder for the deployment-wide effort default.

    ``default_effort`` is ``None`` when no deployment effort has ever been set —
    in that case sessions with no override fall back to the provider's own
    machine-configured default. Mirrors the ``DeploymentModelConfig`` pattern:
    one instance, injected into both the HTTP routes and the dispatcher so a
    ``PUT`` is observed live.
    """

    default_effort: str | None = None


def resolve_effective_effort(
    session_effort: str | None,
    deployment_default: str | None,
) -> str | None:
    """Precedence: session > deployment > None.

    Returns the first non-None value, or None if both levels are unset
    (meaning: omit the effort flag and let the provider pick its own default).
    Unlike ``resolve_effective_model`` there is no task or machine level —
    effort precedence is session + deployment only (issue #60, out of scope).
    """
    for candidate in (session_effort, deployment_default):
        if candidate is not None:
            return candidate
    return None
