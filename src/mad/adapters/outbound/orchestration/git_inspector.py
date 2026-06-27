"""``SubprocessGitInspector`` — production ``GitInspector`` implementation.

Issue #88. Shells out to read-only git plumbing to observe a workspace's git
state. Lives in the adapters layer because ``mad.core`` is subprocess-free
(hard rule 4); the dispatcher depends only on the
``mad.core.orchestration.ports.git_inspector.GitInspector`` Protocol.

Every command is read-only — ``rev-parse``, ``log``, ``status --porcelain``
— and uses only locally-cached refs, so ``inspect`` never touches the network
and never mutates the workspace (issue #88 AC). Any failure (non-git
directory, missing repo, git exiting non-zero, git binary absent) degrades to
``None``; the dispatcher then omits the ``task.git_result`` event rather than
failing the task.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mad.core.orchestration.domain.git_result import Commit, GitResult

# Tab-separated ``<sha>\t<subject>`` per commit. A commit subject cannot
# contain a newline; a literal tab in a subject is vanishingly rare and would
# only split a subject early, never corrupt the SHA.
_LOG_FORMAT = "%H%x09%s"


class SubprocessGitInspector:
    """Read-only git observer backed by ``asyncio.create_subprocess_exec``.

    ``git_bin`` is configurable for tests/operators; defaults to ``"git"`` on
    PATH.
    """

    def __init__(self, git_bin: str = "git") -> None:
        self._git_bin = git_bin

    async def read_head_sha(self, workspace: Path) -> str | None:
        return await self._rev_parse(workspace, "HEAD")

    async def inspect(self, workspace: Path, base_sha: str | None) -> GitResult | None:
        if base_sha is None:
            return None
        head_sha = await self._rev_parse(workspace, "HEAD")
        if head_sha is None:
            # Not a git repo (or git failed) — degrade gracefully.
            return None
        head_branch = await self._current_branch(workspace)
        commits = await self._commits_since(workspace, base_sha)
        dirty = await self._is_dirty(workspace)
        pushed = await self._is_pushed(workspace, head_branch)
        return GitResult(
            base_sha=base_sha,
            head_branch=head_branch,
            head_sha=head_sha,
            commits=commits,
            dirty=dirty,
            pushed=pushed,
        )

    # -- git plumbing ------------------------------------------------------

    async def _run_git(self, workspace: Path, *args: str) -> tuple[int, str] | None:
        """Run ``git -C <workspace> <args...>`` read-only.

        Returns ``(returncode, stdout_text)`` on a clean spawn, or ``None`` if
        the git binary cannot be launched at all (e.g. not installed). The
        caller decides what a non-zero return code means for each command.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._git_bin,
                "-C",
                str(workspace),
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except (OSError, ValueError):
            return None
        stdout, _ = await proc.communicate()
        return proc.returncode or 0, stdout.decode(errors="replace")

    async def _rev_parse(self, workspace: Path, rev: str) -> str | None:
        result = await self._run_git(workspace, "rev-parse", rev)
        if result is None:
            return None
        code, out = result
        if code != 0:
            return None
        sha = out.strip()
        return sha or None

    async def _current_branch(self, workspace: Path) -> str | None:
        """Resolve the current branch, or ``"HEAD"`` when detached.

        ``git rev-parse --abbrev-ref HEAD`` prints the literal ``"HEAD"`` in
        detached state, which is reported verbatim (issue #88 AC: detached
        HEAD does not crash). ``None`` only when git itself fails.
        """
        result = await self._run_git(workspace, "rev-parse", "--abbrev-ref", "HEAD")
        if result is None:
            return None
        code, out = result
        if code != 0:
            return None
        name = out.strip()
        return name or None

    async def _commits_since(self, workspace: Path, base_sha: str) -> tuple[Commit, ...]:
        result = await self._run_git(
            workspace, "log", f"--format={_LOG_FORMAT}", f"{base_sha}..HEAD"
        )
        if result is None:
            return ()
        code, out = result
        if code != 0:
            return ()
        commits: list[Commit] = []
        for line in out.splitlines():
            if not line:
                continue
            sha, _, subject = line.partition("\t")
            commits.append(Commit(sha=sha, subject=subject))
        return tuple(commits)

    async def _is_dirty(self, workspace: Path) -> bool:
        result = await self._run_git(workspace, "status", "--porcelain")
        if result is None:
            return False
        code, out = result
        if code != 0:
            return False
        return bool(out.strip())

    async def _is_pushed(self, workspace: Path, head_branch: str | None) -> bool:
        """True when ``head_branch`` has a remote-tracking ref on ``origin``.

        Detached HEAD (``head_branch`` is ``None`` or ``"HEAD"``) is never
        ``pushed``. Uses the locally-cached ``refs/remotes/origin/<branch>``
        ref — no network round-trip.
        """
        if head_branch is None or head_branch == "HEAD":
            return False
        result = await self._run_git(
            workspace,
            "rev-parse",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{head_branch}",
        )
        if result is None:
            return False
        code, _ = result
        return code == 0
