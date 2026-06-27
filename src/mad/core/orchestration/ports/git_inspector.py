"""GitInspector port — read-only observation of a workspace's git state.

Issue #88. The dispatcher needs to capture the workspace's git state at two
moments — a baseline ``base_sha`` when a task is dispatched, and the full
:class:`GitResult` when it completes — without importing ``subprocess`` into
``mad.core`` (hard rule 4). This port is that seam: the dispatcher depends on
the Protocol; the production ``SubprocessGitInspector`` adapter
(``mad.adapters.outbound.orchestration.git_inspector``) shells out to git.

Both methods are **read-only** (issue #88 AC: git inspection never mutates the
workspace) and **graceful**: a non-git workspace, a missing repo, or any git
failure returns ``None`` rather than raising, so a task is never failed by an
inability to read its git result. The dispatcher omits the
``task.git_result`` event when ``inspect`` returns ``None``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from mad.core.orchestration.domain.git_result import GitResult


class GitInspector(Protocol):
    """Abstract read-only observer of a workspace's git state."""

    async def read_head_sha(self, workspace: Path) -> str | None:
        """Return ``git rev-parse HEAD`` for ``workspace``.

        Captured at dispatch time as the ``base_sha`` baseline. Returns
        ``None`` when ``workspace`` is not a git repository or git fails.
        """
        ...

    async def inspect(self, workspace: Path, base_sha: str | None) -> GitResult | None:
        """Observe the post-run git state of ``workspace`` relative to ``base_sha``.

        Returns a :class:`GitResult` with the resolved branch, head SHA, the
        commit list since ``base_sha``, and the ``dirty``/``pushed`` flags.
        Returns ``None`` when ``workspace`` is not a git repository, when
        ``base_sha`` is ``None`` (no baseline was captured), or when git fails
        — the dispatcher then omits the ``task.git_result`` event.
        """
        ...
