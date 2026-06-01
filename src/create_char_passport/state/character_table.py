"""Canonical ``character_table`` field vocabulary.

``character_table`` is the structured trait sheet of a character (§4 "МИНИМУМ
полей в табличке" / §6 of ``plan/proekt_zametki.md``). It is produced two ways
— extracted from the source text on the start screen, or typed/edited by the
user on the character-data screen — and read back by every later phase. To
keep those producers and consumers from drifting, the field keys live here as
the single source of truth; nobody hardcodes the strings.

The user is always the source of truth: extraction only seeds a *draft*, so
every value is a free-form editable string (gender included). Missing /
``null`` traits collapse to an empty string, never the literal ``"null"``.

# PLAYBOOK-START
# id: shared-field-vocabulary
# title: One field vocabulary shared by every producer and consumer
# status: draft
# category: architecture
# tags: [contracts, schema, drift]
# When the same record is filled by one component and read by several others,
# pin its field keys as a single shared constant and route every side through
# it. Scattered string literals silently drift ("what writer A emits" vs "what
# reader B looks up"); a shared vocabulary makes drift a type/import error.
# PLAYBOOK-END
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class TableField:
    """One row of the character trait sheet — a stable key plus a UI label."""

    key: str
    label: str


CHARACTER_TABLE_FIELDS: tuple[TableField, ...] = (
    TableField("gender", "Gender"),
    TableField("age", "Age"),
    TableField("build", "Build"),
    TableField("hair", "Hair (colour + type)"),
    TableField("eyes", "Eyes"),
    TableField("skin", "Skin tone"),
    TableField("role", "Role / clothing"),
    TableField("details", "Distinctive details"),
)

CHARACTER_TABLE_KEYS: tuple[str, ...] = tuple(field.key for field in CHARACTER_TABLE_FIELDS)

# Values the LLM (or a stale state.json) may use to mean "no value". Compared
# case-insensitively after stripping; everything here becomes "".
_NULLISH: frozenset[str] = frozenset({"", "null", "none", "n/a", "—", "-"})


def coerce_value(value: Any) -> str:
    """Normalise one trait value to a clean string ("" when absent).

    ``None``, the JSON/string ``null``, and a handful of common "empty"
    sentinels all collapse to ``""`` so the form never shows the word
    ``null`` and downstream prompt building can treat blank uniformly.
    """
    if value is None:
        return ""
    text = str(value).strip()
    if text.casefold() in _NULLISH:
        return ""
    return text


def blank_character_table() -> dict[str, str]:
    """A fresh table with every canonical key present and empty."""
    return {key: "" for key in CHARACTER_TABLE_KEYS}


def normalize_character_table(data: dict[str, Any] | None) -> dict[str, str]:
    """Coerce an arbitrary mapping into the canonical, fully-keyed table.

    Unknown keys are dropped, missing keys are added as ``""``, and every
    value passes through :func:`coerce_value`. Safe to call on raw LLM output,
    a loaded ``state.json`` table, or partial form input.
    """
    table = blank_character_table()
    if not data:
        return table
    for key in CHARACTER_TABLE_KEYS:
        table[key] = coerce_value(data.get(key))
    return table
