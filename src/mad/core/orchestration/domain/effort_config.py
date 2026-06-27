"""Deployment-wide reasoning-effort configuration + precedence resolver (issue #60).

Mirrors the DeploymentModelConfig pattern (issue #55) exactly — effort is the
parallel knob to model: one mutable process-global singleton, persisted under a
reserved session log, bootstrapped at startup. ``None`` everywhere means "omit
the effort flag" (``--effort`` for claude, ``--variant`` for opencode) so the
provider uses its own default — Mad imposes no opinion and never enumerates or
validates effort values (opaque pass-through for v1).

Precedence is task > session > deployment (issue #81) — symmetric with
``resolve_effective_model``. A per-task override lets one session's dispatch
queue mix effort levels (cheap docs task vs. high-effort migration) without
opening a session per level.
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
    task_effort: str | None,
    session_effort: str | None,
    deployment_default: str | None,
) -> str | None:
    """Precedence: task > session > deployment > None.

    Returns the first non-None value, or None if every level is unset
    (meaning: omit the effort flag and let the provider pick its own default).
    Mirror of ``resolve_effective_model`` minus the machine level — the
    launcher pass-through has no per-machine effort default (issue #81).
    """
    for candidate in (task_effort, session_effort, deployment_default):
        if candidate is not None:
            return candidate
    return None
