"""Tests for the Space verify API (generation routing endpoints)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from create_char_passport import verify_api
from create_char_passport.gen import GenerationResult


def test_verify_generate_image_passes_layers_refs_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    def fake_gen(layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
        captured["layers"] = dict(layers)
        captured["roles"] = [r.role for r in refs]
        captured["conflict"] = outfit_conflict
        Path(output_path).write_bytes(b"img")
        return GenerationResult(image_path=str(output_path), ok=True)

    monkeypatch.setattr(verify_api, "generate_image", fake_gen)
    ref = tmp_path / "style.png"
    ref.write_bytes(b"x")
    out = verify_api.verify_generate_image('{"style": "grim"}', [str(ref)], '["style"]', True)
    assert Path(out).is_file()
    assert captured["layers"] == {"style": "grim"}
    assert captured["roles"] == ["style"]
    assert captured["conflict"] is True


def test_verify_generate_image_raises_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        verify_api,
        "generate_image",
        lambda *a, **k: GenerationResult(image_path=None, ok=False, error="boom"),
    )
    with pytest.raises(RuntimeError, match="boom"):
        verify_api.verify_generate_image("{}", None, "[]", False)


def test_verify_call_llm_base64s_images(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def fake_llm(prompt, image_b64=None, *, images_b64=None, model=None, meter=None):
        captured["prompt"] = prompt
        captured["n"] = len(images_b64 or [])
        return "hello world"

    monkeypatch.setattr(verify_api, "call_llm", fake_llm)
    img = tmp_path / "i.png"
    img.write_bytes(b"y")
    assert verify_api.verify_call_llm("hi", [str(img)]) == "hello world"
    assert captured["prompt"] == "hi"
    assert captured["n"] == 1
    # Text-only (no images) is allowed.
    assert verify_api.verify_call_llm("hi", None) == "hello world"
    assert captured["n"] == 0
