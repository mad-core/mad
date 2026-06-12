"""Deployment-wide dispatch policy (issue #45 / ADR-0009 amendment).

Issue #33 shipped a *per-session* dispatch policy. This module adds a
single process-global default that every session inherits unless it pins
its own override:

    effective policy = session.dispatch_policy
                       or deployment_default
                       or ImmediatePolicy()

There is no first-class ``Workspace`` entity (ADR-0006 — multi-tenancy
deferred). "Workspace-level" here means one default for the whole Mad
instance, exposed at the bare ``/v1/dispatch_policy`` (no id). A named
multi-workspace model belongs to the future multi-tenancy module.

Persistence (hard rule 6). The deployment default is persisted to a
reserved session log (``DEPLOYMENT_SESSION_ID``) via the same
``EventEmitter`` path everything else uses, so it is replayed on restart.
The reserved id is excluded from ``list_session_ids`` so it never shows up
as a real session.
"""

from __future__ import annotations

from dataclasses import dataclass

from mad.core.orchestration.domain.dispatch_policy import (
    DispatchPolicy,
    ImmediatePolicy,
)
from mad.core.sessions.domain.entities.session import Session

# Reserved "session" id under which the deployment-wide default policy is
# persisted. The leading double underscore marks it as an internal stream
# that ``JsonlSessionRepository.list_session_ids`` filters out, so it is
# never rehydrated or listed as a user session.
DEPLOYMENT_SESSION_ID = "__deployment__"


@dataclass
class DeploymentDispatchPolicy:
    """Mutable process-global holder for the deployment-wide default.

    ``default`` is ``None`` when no deployment policy has ever been set —
    in that case sessions with no override fall back to ``ImmediatePolicy``.
    Mirrors the ``SessionStore`` pattern: one instance, injected into both
    the HTTP routes and the dispatcher so a ``PUT`` is observed live.
    """

    default: DispatchPolicy | None = None


def resolve_effective_policy(
    session: Session,
    deployment: DeploymentDispatchPolicy | None,
) -> DispatchPolicy:
    """Return the policy that actually governs ``session`` right now.

    Resolution order (issue #45): the session's own override, else the
    deployment default, else ``ImmediatePolicy`` (unchanged legacy
    behaviour when nothing is configured anywhere).
    """
    if session.dispatch_policy is not None:
        return session.dispatch_policy
    if deployment is not None and deployment.default is not None:
        return deployment.default
    return ImmediatePolicy()
