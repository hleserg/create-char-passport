"""Unit tests for the trait-table -> layer-prompts composer (no network)."""

from __future__ import annotations

import pytest

from create_char_passport.wizard import compose as compose_mod
from create_char_passport.wizard.compose import (
    ComposedLayers,
    build_compose_prompt,
    compose_layers,
    parse_compose_response,
)

_TABLE = {"gender": "male", "age": "40", "details": "scar on cheek, anchor tattoo on forearm"}


def test_build_compose_prompt_embeds_table() -> None:
    prompt = build_compose_prompt(_TABLE)
    assert "scar on cheek" in prompt
    assert prompt.strip().endswith("}") or "anchor tattoo" in prompt


def test_parse_valid_json() -> None:
    raw = (
        '{"face": "broad nose, scar on cheek", "body": "stocky, anchor tattoo",'
        ' "outfit": "leather tunic", "base_emotion": "grim, brooding"}'
    )
    layers = parse_compose_response(raw)
    assert layers.face == "broad nose, scar on cheek"
    assert layers.body == "stocky, anchor tattoo"
    assert layers.outfit == "leather tunic"
    assert layers.base_emotion == "grim, brooding"


def test_parse_tolerates_fences_and_junk() -> None:
    fenced = '```json\n{"face": "x", "body": "", "outfit": "", "base_emotion": ""}\n```'
    assert parse_compose_response(fenced).face == "x"
    assert parse_compose_response("not json at all") == ComposedLayers()
    assert parse_compose_response("[]") == ComposedLayers()
    assert parse_compose_response("") == ComposedLayers()


def test_compose_layers_empty_table_no_call(monkeypatch: pytest.MonkeyPatch) -> None:
    called = []
    monkeypatch.setattr(compose_mod, "call_llm", lambda *a, **k: called.append(1) or "")
    assert compose_layers({}) == ComposedLayers()
    assert compose_layers({"gender": "", "age": ""}) == ComposedLayers()
    assert not called  # short-circuited, no paid call


def test_compose_layers_calls_llm_and_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        compose_mod,
        "call_llm",
        lambda *a, **k: '{"face":"f","body":"b","outfit":"o","base_emotion":"calm"}',
    )
    layers = compose_layers(_TABLE)
    assert (layers.face, layers.body, layers.outfit, layers.base_emotion) == ("f", "b", "o", "calm")
