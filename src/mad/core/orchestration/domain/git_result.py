"""Git-result value objects for the orchestration module.

Issue #88. After a dispatched task completes, Mad observes the workspace's
git state — which branch the work landed on and which commits the agent
created — and records it as a ``task.git_result`` event. This is filesystem
observation, **not** agent-output parsing (hard rule 1): the external agent
makes the commits; Mad only reads the result afterward, the same category as
the token-stripping git operations in ``materialize_github_repo``.

These are pure value objects — no I/O, no framework imports (hard rule 4).
The ``GitInspector`` port produces them; the dispatcher serializes them onto
the event log via :meth:`GitResult.to_event_data`.

The shape is deliberately metadata-only (SHA + subject), never diff or commit
*contents* (hard rule 1 / issue #88 out-of-scope). ``pushed`` is the flag the
downstream branch-propagation feature (#90) consumes to decide whether a
dependent session can re-clone the produced branch.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Commit:
    """A single commit the agent created during the task run.

    ``sha`` is the full 40-char hex object name; ``subject`` is the first
    line of the commit message verbatim. No body, no diff (hard rule 1).
    """

    sha: str
    subject: str


@dataclass(frozen=True)
class GitResult:
    """The git state observed in a session workspace after a task completes.

    ``base_sha`` is HEAD captured at dispatch time (before the agent ran);
    ``head_sha`` is HEAD after. ``head_branch`` is the current branch name,
    or ``"HEAD"`` when the workspace is in detached-HEAD state (reported, not
    crashed — issue #88 AC). ``commits`` lists everything in
    ``base_sha..head_sha`` in reverse-chronological order, possibly empty (a
    task that created no commits still produces a result — the negative twin).
    ``dirty`` is True when uncommitted changes remain in the working tree;
    ``pushed`` is True when ``head_branch`` exists on ``origin``.
    """

    base_sha: str
    head_branch: str | None
    head_sha: str
    commits: tuple[Commit, ...]
    dirty: bool
    pushed: bool

    def to_event_data(self, task_id: str) -> dict[str, object]:
        """Serialize to the ``task.git_result`` event ``data`` payload.

        The ``task_id`` is supplied by the dispatcher (it owns the in-flight
        identity) rather than carried on the value object, keeping this type a
        pure projection of git state.
        """
        return {
            "task_id": task_id,
            "base_sha": self.base_sha,
            "head_branch": self.head_branch,
            "head_sha": self.head_sha,
            "commits": [{"sha": c.sha, "subject": c.subject} for c in self.commits],
            "dirty": self.dirty,
            "pushed": self.pushed,
        }
