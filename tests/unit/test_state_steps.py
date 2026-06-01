"""Tests for K1 step_key vocabulary and ordering."""

from __future__ import annotations

import pytest

from create_char_passport.state import (
    BASE_EMOTION_STEP,
    PASSPORT_STEPS,
    EmotionItem,
    OutfitDetail,
    OutfitEntry,
    PropEntry,
    PropShot,
    StepKind,
    blank_state,
    classify_step,
    dataset_step,
    emotion_step,
    is_passport_step,
    ordered_step_keys,
    outfit_detail_step,
    outfit_step,
    prop_shot_step,
    slugify,
)


def test_passport_steps_canonical_order() -> None:
    assert PASSPORT_STEPS == (
        "passport_face",
        "passport_body",
        "passport_profile",
        "passport_back",
        "passport_3q",
    )


def test_slugify_handles_punctuation_and_unicode() -> None:
    assert slugify("Angry, Furious!") == "angry_furious"
    assert slugify("Übermensch — calm") == "ubermensch_calm"
    assert slugify("   ") == "x"


def test_step_key_constructors() -> None:
    assert emotion_step("smiling warmly") == "emotion_smiling_warmly"
    assert outfit_step("outfit_1") == "outfit_outfit_1"
    assert outfit_detail_step("o1", 2) == "outfit_o1_detail_2"
    assert prop_shot_step("p1", 1) == "prop_p1_shot_1"
    assert dataset_step(5) == "dataset_5"


@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("passport_face", StepKind.PASSPORT),
        ("base_emotion", StepKind.BASE_EMOTION),
        ("emotion_neutral", StepKind.EMOTION),
        ("outfit_o1", StepKind.OUTFIT),
        ("outfit_o1_detail_1", StepKind.OUTFIT_DETAIL),
        ("prop_p1_shot_1", StepKind.PROP),
        ("dataset_0", StepKind.DATASET),
    ],
)
def test_classify_step(key: str, expected: StepKind) -> None:
    assert classify_step(key) is expected


def test_classify_step_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown step_key"):
        classify_step("bogus")


def test_is_passport_step() -> None:
    assert is_passport_step("passport_face") is True
    assert is_passport_step("emotion_neutral") is False


def test_ordered_step_keys_minimal_state() -> None:
    state = blank_state("Heron")
    assert ordered_step_keys(state) == list(PASSPORT_STEPS)


def test_ordered_step_keys_full_state() -> None:
    state = blank_state("Heron")
    state.emotions.enabled = True
    state.emotions.items = [
        EmotionItem(value="neutral"),
        EmotionItem(value="angry, furious"),
        EmotionItem(value="smiling warmly"),
    ]
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "calm, composed"
    state.outfits_enabled = True
    state.outfits = [
        OutfitEntry(id="o1", details=[OutfitDetail(prompt="belt buckle")]),
        OutfitEntry(id="o2"),
    ]
    state.props_enabled = True
    state.props = [PropEntry(id="p1", shots=[PropShot(what="sword"), PropShot(what="sheath")])]
    state.dataset_compositions = ["walking", "sitting"]

    keys = ordered_step_keys(state)
    assert keys[:5] == list(PASSPORT_STEPS)
    assert BASE_EMOTION_STEP in keys
    base_idx = keys.index(BASE_EMOTION_STEP)
    # Series emotions follow the base emotion key and keep their array order.
    assert keys[base_idx + 1] == "emotion_neutral"
    assert keys[base_idx + 2] == "emotion_angry_furious"
    assert keys[base_idx + 3] == "emotion_smiling_warmly"
    # Outfits come after emotions, details follow each outfit.
    assert "outfit_o1" in keys
    assert "outfit_o1_detail_1" in keys
    # Props come next.
    assert "prop_p1_shot_1" in keys and "prop_p1_shot_2" in keys
    # Dataset compositions close out.
    assert keys[-2:] == ["dataset_0", "dataset_1"]


def test_ordered_step_keys_base_emotion_only_via_toggle() -> None:
    state = blank_state("Heron")
    state.emotions.base_emotion.enabled = True
    keys = ordered_step_keys(state)
    assert BASE_EMOTION_STEP in keys
    # No emotion series keys because emotions.enabled is False.
    assert not any(k.startswith("emotion_") for k in keys)
