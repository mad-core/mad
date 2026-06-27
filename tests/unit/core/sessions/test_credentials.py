"""Unit tests for host-env clone-credential resolution (issue #89).

The autouse ``_isolate_clone_credentials`` fixture (tests/conftest.py) clears
``GITHUB_TOKEN`` / ``GH_TOKEN`` before each test, so every case starts from a
known-empty environment and sets only what it asserts on.
"""

from __future__ import annotations

import pytest

from mad.core.sessions.credentials import host_github_token, resolve_clone_token


def test_host_token_reads_github_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_from_github_token")
    assert host_github_token() == "ghp_from_github_token"


def test_host_token_falls_back_to_gh_token_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    """GH_TOKEN is the documented alias (matches git/gh) when GITHUB_TOKEN is unset."""
    monkeypatch.setenv("GH_TOKEN", "ghp_from_gh_token")
    assert host_github_token() == "ghp_from_gh_token"


def test_host_token_prefers_github_token_over_gh_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_primary")
    monkeypatch.setenv("GH_TOKEN", "ghp_alias")
    assert host_github_token() == "ghp_primary"


def test_host_token_none_when_unset() -> None:
    """Negative twin: no host credential configured returns None (not a crash)."""
    assert host_github_token() is None


def test_host_token_treats_blank_github_token_as_unset(monkeypatch: pytest.MonkeyPatch) -> None:
    """A blank GITHUB_TOKEN must not mask the GH_TOKEN alias."""
    monkeypatch.setenv("GITHUB_TOKEN", "   ")
    monkeypatch.setenv("GH_TOKEN", "ghp_alias")
    assert host_github_token() == "ghp_alias"


def test_resolve_uses_env_when_no_inline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    assert resolve_clone_token(None) == "ghp_env"


def test_resolve_inline_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defined precedence: an explicit (deprecated) inline token wins over host env."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    assert resolve_clone_token("ghp_inline") == "ghp_inline"


def test_resolve_blank_inline_falls_through_to_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Negative twin of precedence: a blank inline value is not 'supplied'."""
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_env")
    assert resolve_clone_token("   ") == "ghp_env"


def test_resolve_none_when_neither_present() -> None:
    """Negative twin: no inline and no host credential resolves to None."""
    assert resolve_clone_token(None) is None
