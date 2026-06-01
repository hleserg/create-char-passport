"""Tests for the style-drafting pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.state import blank_state
from create_char_passport.storage import character_asset
from create_char_passport.wizard import style
from create_char_passport.wizard.style import apply_style, draft_style_prompt, set_style_ref


def test_draft_style_sends_all_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = []
    for i in range(3):
        p = tmp_path / f"ref{i}.png"
        p.write_bytes(f"bytes-{i}".encode())
        paths.append(str(p))

    captured: dict[str, object] = {}

    def fake_call_llm(prompt: str, *, images_b64: list[str] | None = None, **_: object) -> str:
        captured["prompt"] = prompt
        captured["images"] = images_b64
        return "  inked grim comic style  "

    monkeypatch.setattr(style, "call_llm", fake_call_llm)
    result = draft_style_prompt(paths)
    assert result == "inked grim comic style"  # stripped
    assert isinstance(captured["images"], list)
    assert len(captured["images"]) == 3  # type: ignore[arg-type]


def test_draft_style_no_images_skips_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> str:  # pragma: no cover - must not run
        raise AssertionError("call_llm should not run without images")

    monkeypatch.setattr(style, "call_llm", boom)
    assert draft_style_prompt([]) == ""
    assert draft_style_prompt(["", None]) == ""  # type: ignore[list-item]


def test_apply_style_writes_layer() -> None:
    state = blank_state("Conan")
    apply_style(state, "  painted illustration  ")
    assert state.prompt_layers.style == "painted illustration"


def test_set_style_ref_copies_image(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    src = tmp_path / "comic.png"
    src.write_bytes(b"comic-bytes")
    state = blank_state("Conan")
    rel = set_style_ref(state, str(src))
    assert rel == "refs/style.png"
    assert state.style_ref == "refs/style.png"
    dest = character_asset(state.character_id, "refs/style.png")
    assert dest.is_file()
    assert dest.read_bytes() == b"comic-bytes"  # the image was actually copied in


def test_set_style_ref_noop_on_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    state = blank_state("Conan")
    assert set_style_ref(state, None) is None
    assert set_style_ref(state, "") is None
    assert set_style_ref(state, str(tmp_path / "nope.png")) is None
    assert state.style_ref is None  # nothing recorded on a missing source
