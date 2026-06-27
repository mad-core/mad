"""Clone-credential resolution from the host environment (issue #89).

Establishes Mad's configuration principle for *access* to external services:
credentials are sourced from the host's system environment using each
ecosystem's **generic, conventional** variable name — NOT a ``MAD_``-prefixed
name. The ``MAD_*`` namespace is reserved for Mad's own *operational tuning*
(``MAD_AGENT_TIMEOUT_S``, ``MAD_CLAUDE_CLI_BIN``, …). Access credentials follow
the upstream convention instead, so for GitHub that is the standard
``GITHUB_TOKEN``, with ``GH_TOKEN`` accepted as an alias to match ``git`` / ``gh``
tooling.

This module only *resolves* which token string to use. Token hygiene (hard
rule 2) is unchanged and stays in the provisioner: the token is used for
``git clone`` then stripped from the remote, and is never persisted to the
workspace, session log, or stdout.
"""

from __future__ import annotations

import os

#: Host environment variables consulted for the GitHub clone PAT, in order.
GITHUB_TOKEN_ENV_VARS: tuple[str, ...] = ("GITHUB_TOKEN", "GH_TOKEN")


def host_github_token() -> str | None:
    """Return the GitHub clone PAT from the host environment, or ``None``.

    Consults ``GITHUB_TOKEN`` first, then ``GH_TOKEN``. An empty or
    whitespace-only value is treated as unset so an exported-but-blank var
    does not mask the alias.
    """
    for name in GITHUB_TOKEN_ENV_VARS:
        value = os.environ.get(name)
        if value and value.strip():
            return value
    return None


def resolve_clone_token(inline: str | None) -> str | None:
    """Resolve the effective clone token for a ``github_repository`` resource.

    Precedence: an explicit (deprecated) ``inline`` token wins when supplied;
    otherwise fall back to the host environment (``GITHUB_TOKEN``, then
    ``GH_TOKEN``). Returns ``None`` when neither is present — the caller then
    clones anonymously, which succeeds for public repositories and fails with
    an actionable error for private ones (never a silent 404).
    """
    if inline and inline.strip():
        return inline
    return host_github_token()
