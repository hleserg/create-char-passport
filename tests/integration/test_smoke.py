"""Integration smoke test placeholder."""

from __future__ import annotations

import pytest

from create_char_passport import __version__


@pytest.mark.integration
def test_version_present() -> None:
    assert __version__
