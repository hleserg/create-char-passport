"""Tests for the base-emotion presets."""

from __future__ import annotations

from create_char_passport.wizard import (
    BASE_EMOTION_PRESETS,
    preset_labels,
    value_for_label,
)


def test_twelve_presets_with_unique_values() -> None:
    assert len(BASE_EMOTION_PRESETS) == 12
    values = [p.value for p in BASE_EMOTION_PRESETS]
    assert len(set(values)) == 12


def test_labels_combine_value_and_description() -> None:
    labels = preset_labels()
    assert len(labels) == 12
    assert any(label.startswith("grim, brooding — ") for label in labels)


def test_value_for_label_resolves_and_passes_through() -> None:
    grim = next(p for p in BASE_EMOTION_PRESETS if p.value == "grim, brooding")
    assert value_for_label(grim.label) == "grim, brooding"
    # A free-typed value (not a preset label) passes through unchanged.
    assert value_for_label("my own expression") == "my own expression"
