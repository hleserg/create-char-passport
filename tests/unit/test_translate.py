"""Unit tests for the RU->EN layer translator (no network)."""

from __future__ import annotations

import pytest

from create_char_passport.wizard import translate as tr
from create_char_passport.wizard.translate import (
    Translation,
    build_translate_prompt,
    parse_translation,
    translate_layer,
)


def test_build_prompt_embeds_text_and_layer() -> None:
    p = build_translate_prompt("тёмная кожаная туника", "Одежда")
    assert "тёмная кожаная туника" in p
    assert "'Одежда' layer" in p  # {layer} substituted


def test_build_prompt_edit_mode_embeds_current_and_change_instruction() -> None:
    p = build_translate_prompt("сделай нос покрупнее", "face", current="broad nose, full lips")
    assert "сделай нос покрупнее" in p  # the change request
    assert "broad nose, full lips" in p  # the existing prompt to modify
    assert "MODIFYING" in p and "do NOT rewrite from scratch" in p
    assert "{current}" not in p  # placeholder fully substituted


def test_build_prompt_blank_current_stays_fresh_translate() -> None:
    # A whitespace-only current must NOT switch to edit mode.
    p = build_translate_prompt("широкий нос", "face", current="   ")
    assert "MODIFYING" not in p


def test_parse_valid_json_with_suggestions() -> None:
    raw = '{"text": "dark leather tunic", "suggestions": {"body": "stocky build", "x": "ignored"}}'
    t = parse_translation(raw)
    assert t.text == "dark leather tunic"
    assert t.suggestions == {"body": "stocky build"}  # unknown keys dropped


def test_parse_non_json_becomes_text() -> None:
    assert parse_translation("dark leather tunic").text == "dark leather tunic"
    assert parse_translation("[]").text == "[]"
    assert parse_translation("") == Translation()


def test_translate_empty_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(tr, "call_llm", lambda *a, **k: called.append(1) or "")
    assert translate_layer("", "Лицо") == Translation()
    assert translate_layer("   ", "Лицо") == Translation()
    assert not called


def test_translate_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        tr, "call_llm", lambda *a, **k: '{"text": "broad nose", "suggestions": {"outfit": "tunic"}}'
    )
    t = translate_layer("широкий нос", "Лицо")
    assert t.text == "broad nose"
    assert t.suggestions == {"outfit": "tunic"}


def test_translate_edit_mode_forwards_current(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}
    monkeypatch.setattr(
        tr, "call_llm", lambda prompt, **k: seen.update(prompt=prompt) or '{"text": "bigger nose"}'
    )
    t = translate_layer("сделай нос покрупнее", "face", current="broad nose")
    assert t.text == "bigger nose"
    # The existing prompt + edit instruction reach the LLM (modify, not rewrite).
    assert "broad nose" in seen["prompt"]
    assert "MODIFYING" in seen["prompt"]
