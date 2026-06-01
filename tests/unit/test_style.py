"""Tests for the style-drafting pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from create_char_passport.state import blank_state
from create_char_passport.wizard import style
from create_char_passport.wizard.style import apply_style, draft_style_prompt


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
