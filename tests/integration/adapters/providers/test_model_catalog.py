"""Integration tests for ModelCatalogAdapter.

Coverage:
- claude_cli always returns the static fallback list.
- opencode: successful dynamic discovery with a fake binary.
- opencode: binary unavailable → fallback (negative twin).
- opencode: binary exits non-zero → fallback (negative twin of success).
- opencode: binary exits 0 with empty output → fallback.
"""

from __future__ import annotations

import stat
import textwrap
from pathlib import Path

import pytest

from mad.adapters.outbound.agents.model_catalog import (
    _CLAUDE_CLI_FALLBACK,
    _OPENCODE_FALLBACK,
    ModelCatalogAdapter,
)


def _make_executable_script(path: Path, source: str) -> Path:
    """Write a Python shebang script, make it executable, and return its path."""
    path.write_text("#!/usr/bin/env python3\n" + textwrap.dedent(source))
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


@pytest.mark.asyncio
async def test_claude_cli_returns_static_fallback() -> None:
    """claude_cli key is always present and equals the documented static fallback."""
    adapter = ModelCatalogAdapter()
    result = await adapter.discover()

    assert "claude_cli" in result
    assert result["claude_cli"] == list(_CLAUDE_CLI_FALLBACK)


@pytest.mark.asyncio
async def test_opencode_dynamic_discovery_with_fake_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """opencode: fake binary printing two model ids → discover() returns exactly those ids."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode",
        """\
        print("anthropic/claude-sonnet-99")
        print("openai/gpt-5-turbo")
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    adapter = ModelCatalogAdapter()
    result = await adapter.discover()

    assert "opencode" in result
    assert result["opencode"] == ["anthropic/claude-sonnet-99", "openai/gpt-5-turbo"]


@pytest.mark.asyncio
async def test_opencode_binary_unavailable_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEGATIVE TWIN: opencode binary absent → discover()['opencode'] equals the fallback list."""
    monkeypatch.delenv("MAD_OPENCODE_BIN", raising=False)
    # Point PATH at an empty directory so shutil.which("opencode") returns None.
    monkeypatch.setenv("PATH", str(tmp_path))

    adapter = ModelCatalogAdapter()
    result = await adapter.discover()

    assert "opencode" in result
    assert result["opencode"] == list(_OPENCODE_FALLBACK)


@pytest.mark.asyncio
async def test_opencode_nonzero_exit_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """NEGATIVE TWIN: opencode binary exits non-zero → fallback, not exception."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode_fail",
        """\
        import sys
        print("something")
        sys.exit(1)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    adapter = ModelCatalogAdapter()
    result = await adapter.discover()

    assert "opencode" in result
    assert result["opencode"] == list(_OPENCODE_FALLBACK)


@pytest.mark.asyncio
async def test_opencode_empty_output_returns_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """opencode binary exits 0 with no output lines → fallback (empty result guard)."""
    fake_bin = _make_executable_script(
        tmp_path / "fake_opencode_empty",
        """\
        import sys
        sys.exit(0)
        """,
    )
    monkeypatch.setenv("MAD_OPENCODE_BIN", str(fake_bin))

    adapter = ModelCatalogAdapter()
    result = await adapter.discover()

    assert "opencode" in result
    assert result["opencode"] == list(_OPENCODE_FALLBACK)
