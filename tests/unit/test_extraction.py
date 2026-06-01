"""Tests for the tolerant character-extraction pipeline."""

from __future__ import annotations

import pytest

from create_char_passport.state import CHARACTER_TABLE_KEYS
from create_char_passport.wizard import extraction
from create_char_passport.wizard.extraction import (
    build_extraction_prompt,
    extract_characters,
    parse_extraction_response,
)

_CLEAN = """
[
  {"name": "Conan", "gender": "male", "age": "around 30", "build": "powerful",
   "hair": "black, shoulder-length", "eyes": "blue", "skin": null,
   "role": "warrior", "details": "scar on left cheek",
   "face": "broad face, straight nose, blue eyes, black shoulder-length hair",
   "body": "powerful, stocky build, scar on left forearm",
   "outfit": "dark fur-trimmed leather tunic"},
  {"name": "the old fisherman", "gender": "male", "age": "old", "build": null,
   "hair": null, "eyes": null, "skin": null, "role": "fisherman", "details": null,
   "face": null, "body": null, "outfit": null}
]
"""


def test_build_prompt_embeds_text_and_schema() -> None:
    prompt = build_extraction_prompt("  Once upon a time  ")
    assert prompt.endswith("Once upon a time")
    assert '"name"' in prompt
    assert "JSON array" in prompt


def test_parse_clean_json_maps_traits_and_nulls() -> None:
    chars = parse_extraction_response(_CLEAN)
    assert [c.name for c in chars] == ["Conan", "the old fisherman"]
    conan = chars[0]
    assert set(conan.table) == set(CHARACTER_TABLE_KEYS)
    assert conan.table["build"] == "powerful"
    assert conan.table["skin"] == ""  # JSON null -> ""
    assert chars[1].table["details"] == ""


def test_parse_extracts_draft_layer_prompts() -> None:
    conan, fisherman = parse_extraction_response(_CLEAN)
    assert conan.face == "broad face, straight nose, blue eyes, black shoulder-length hair"
    assert conan.body == "powerful, stocky build, scar on left forearm"
    assert conan.outfit == "dark fur-trimmed leather tunic"
    # null drafts collapse to "" (not the literal "null")
    assert (fisherman.face, fisherman.body, fisherman.outfit) == ("", "", "")


def test_parse_missing_draft_keys_default_empty() -> None:
    # Older / partial replies without face/body/outfit must not break.
    chars = parse_extraction_response('[{"name": "Tyra", "gender": "female"}]')
    assert (chars[0].face, chars[0].body, chars[0].outfit) == ("", "", "")


def test_parse_strips_markdown_fences() -> None:
    fenced = '```json\n[{"name": "Lucius"}]\n```'
    chars = parse_extraction_response(fenced)
    assert [c.name for c in chars] == ["Lucius"]
    assert chars[0].table["gender"] == ""


def test_parse_skips_nameless_and_non_objects() -> None:
    raw = '[{"name": ""}, "garbage", {"gender": "female"}, {"name": "Tyra"}]'
    chars = parse_extraction_response(raw)
    assert [c.name for c in chars] == ["Tyra"]


def test_parse_broken_json_falls_back_to_names() -> None:
    # Truncated / invalid JSON but names are recoverable.
    broken = '[{"name": "Conan", "gender": "male"}, {"name": "Tyra", oops'
    chars = parse_extraction_response(broken)
    assert [c.name for c in chars] == ["Conan", "Tyra"]
    # Fallback yields empty (but fully-keyed) tables.
    assert all(v == "" for v in chars[0].table.values())


def test_parse_dedupes_names_in_fallback() -> None:
    broken = '{"name": "Conan"} {"name": "Conan"} <<<'
    chars = parse_extraction_response(broken)
    assert [c.name for c in chars] == ["Conan"]


def test_parse_empty_and_unsalvageable() -> None:
    assert parse_extraction_response("") == []
    assert parse_extraction_response("   ") == []
    assert parse_extraction_response("totally not json, no names here") == []


def test_extract_characters_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_call_llm(prompt: str, **_: object) -> str:
        captured["prompt"] = prompt
        return _CLEAN

    monkeypatch.setattr(extraction, "call_llm", fake_call_llm)
    chars = extract_characters("a story")
    assert [c.name for c in chars] == ["Conan", "the old fisherman"]
    assert "a story" in captured["prompt"]


def test_extract_characters_empty_text_skips_call(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_: object, **__: object) -> str:  # pragma: no cover - must not run
        raise AssertionError("call_llm should not be invoked for empty input")

    monkeypatch.setattr(extraction, "call_llm", boom)
    assert extract_characters("   ") == []


def test_extract_characters_api_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(extraction, "call_llm", lambda *_a, **_k: "")
    assert extract_characters("a story") == []
