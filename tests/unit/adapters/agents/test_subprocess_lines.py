"""Unit tests for ``_iter_stdout_lines`` — the robust subprocess line reader.

Regression coverage for issue #70: a single stdout line larger than asyncio's
default StreamReader buffer used to raise ``LimitOverrunError`` out of the
``async for`` loop and kill the launcher task. ``_iter_stdout_lines`` must:
  - yield normal lines decoded and newline-stripped, in order;
  - keep a long-but-bounded line (<= the buffer limit) intact (the case the
    production 64 MB limit protects);
  - drop a line that exceeds the limit instead of raising, so the rest of the
    stream is still read (the negative twin of the case above).
"""

from __future__ import annotations

import asyncio

import pytest

from mad.adapters.outbound.agents._subprocess import (
    _STDOUT_BUFFER_LIMIT,
    _iter_stdout_lines,
)


async def _collect(reader: asyncio.StreamReader) -> list[str]:
    """Drain a (already EOF-fed) reader through the helper into a list.

    The reader is fed EOF by every caller before this runs, so the async
    iterator terminates deterministically (rule 8 — no unbounded loops).
    """
    return [line async for line in _iter_stdout_lines(reader)]


def test_stdout_buffer_limit_is_64_mib() -> None:
    """The buffer ceiling is 64 MB — far above asyncio's 64 KB default that the
    bug overflowed, while still bounding per-stream memory (issue #70)."""
    assert _STDOUT_BUFFER_LIMIT == 64 * 1024 * 1024


@pytest.mark.asyncio
async def test_iter_stdout_lines_yields_normal_lines_stripped_and_ordered() -> None:
    reader = asyncio.StreamReader()
    reader.feed_data(b"first\nsecond\nthird\n")
    reader.feed_eof()

    lines = await _collect(reader)

    assert lines == ["first", "second", "third"]


@pytest.mark.asyncio
async def test_iter_stdout_lines_emits_final_line_without_trailing_newline() -> None:
    """A stream whose last line has no terminating newline still yields it."""
    reader = asyncio.StreamReader()
    reader.feed_data(b"complete\npartial")
    reader.feed_eof()

    lines = await _collect(reader)

    assert lines == ["complete", "partial"]


@pytest.mark.asyncio
async def test_iter_stdout_lines_keeps_line_within_limit_intact() -> None:
    """A long line that fits under the buffer limit is yielded whole."""
    reader = asyncio.StreamReader(limit=10_000)
    payload = "x" * 5_000
    reader.feed_data(payload.encode() + b"\n")
    reader.feed_eof()

    lines = await _collect(reader)

    assert lines == [payload]
    assert len(lines[0]) == 5_000


@pytest.mark.asyncio
async def test_iter_stdout_lines_drops_line_exceeding_limit_without_raising() -> None:
    """Negative twin: a line larger than the limit is skipped, not raised — and
    the lines around it still come through (issue #70 used to crash here)."""
    reader = asyncio.StreamReader(limit=16)
    oversized = "y" * 200
    reader.feed_data(b"before\n" + oversized.encode() + b"\n" + b"after\n")
    reader.feed_eof()

    lines = await _collect(reader)

    assert lines == ["before", "after"]
    assert oversized not in lines
