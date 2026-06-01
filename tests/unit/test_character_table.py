"""Tests for the canonical character_table vocabulary."""

from __future__ import annotations

from create_char_passport.state import (
    CHARACTER_TABLE_FIELDS,
    CHARACTER_TABLE_KEYS,
    blank_character_table,
    coerce_value,
    normalize_character_table,
)


def test_keys_match_fields_and_cover_the_spec() -> None:
    assert tuple(f.key for f in CHARACTER_TABLE_FIELDS) == CHARACTER_TABLE_KEYS
    assert set(CHARACTER_TABLE_KEYS) == {
        "gender",
        "age",
        "build",
        "hair",
        "eyes",
        "skin",
        "role",
        "details",
    }


def test_coerce_value_collapses_nullish() -> None:
    for nullish in (None, "null", "NULL", "none", "n/a", "", "  ", "—", "-"):
        assert coerce_value(nullish) == ""
    assert coerce_value("  scar on cheek ") == "scar on cheek"
    assert coerce_value(30) == "30"


def test_blank_table_has_all_keys_empty() -> None:
    table = blank_character_table()
    assert set(table) == set(CHARACTER_TABLE_KEYS)
    assert all(value == "" for value in table.values())


def test_normalize_drops_unknown_keys_and_cleans_values() -> None:
    raw = {"gender": "male", "age": "null", "weapon": "sword", "details": None}
    table = normalize_character_table(raw)
    assert set(table) == set(CHARACTER_TABLE_KEYS)
    assert table["gender"] == "male"
    assert table["age"] == ""  # "null" string cleaned
    assert table["details"] == ""  # None cleaned
    assert "weapon" not in table  # unknown key dropped


def test_normalize_none_returns_blank() -> None:
    assert normalize_character_table(None) == blank_character_table()
