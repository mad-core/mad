from __future__ import annotations

import pytest

from mad.providers.factory import get_launcher


def test_get_launcher_unknown_name_raises():
    """Unknown / removed provider names must raise NotImplementedError."""
    with pytest.raises(NotImplementedError):
        get_launcher("anthropic_api")


def test_get_launcher_garbage_raises():
    with pytest.raises(NotImplementedError):
        get_launcher("does_not_exist")
