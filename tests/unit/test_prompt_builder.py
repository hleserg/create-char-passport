"""Tests for the K3 prompt builder."""

from __future__ import annotations

import pytest

from create_char_passport.gen import build_prompt_layers, render_prompt_text
from create_char_passport.gen.prompt import LAYER_NAMES, to_prompt_layers
from create_char_passport.state import (
    BaseOutfit,
    CharacterState,
    EmotionItem,
    OutfitEntry,
    PromptLayers,
    blank_state,
)


def make_state() -> CharacterState:
    state = blank_state("Heron")
    state.prompt_layers = PromptLayers(
        style="grim comic style",
        face="broad nose, deep-set dark eyes",
        body="stocky, powerful build",
        outfit="leather tunic",
        expression="brooding",
        composition="full-length, neutral grey background",
    )
    state.base_outfit = BaseOutfit(prompt="leather tunic")
    return state


def test_passport_step_forces_neutral_expression() -> None:
    state = make_state()
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "grim, brooding"

    layers = build_prompt_layers(state, "passport_face")
    assert layers["expression"] == "neutral"


def test_emotion_step_uses_series_value() -> None:
    state = make_state()
    state.emotions.items = [EmotionItem(value="angry, furious")]
    state.emotions.enabled = True

    layers = build_prompt_layers(state, "emotion_angry_furious")
    assert layers["expression"] == "angry furious"


def test_emotion_step_with_blank_suffix_falls_back_to_neutral() -> None:
    state = make_state()
    layers = build_prompt_layers(state, "emotion_")
    assert layers["expression"] == "neutral"


def test_outfit_step_uses_base_emotion_when_set() -> None:
    state = make_state()
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "grim, brooding"
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="armor", prompt="lamellar armor")]
    state.active_outfit_id = "armor"

    layers = build_prompt_layers(state, "outfit_armor")
    assert layers["expression"] == "grim, brooding"
    assert layers["outfit"] == "lamellar armor"


def test_outfit_step_falls_back_to_neutral_when_base_emotion_off() -> None:
    state = make_state()
    state.emotions.base_emotion.enabled = False
    state.emotions.base_emotion.value = "grim, brooding"  # value present but flag off

    layers = build_prompt_layers(state, "outfit_o1")
    assert layers["expression"] == "neutral"


def test_unknown_active_outfit_falls_back_to_base() -> None:
    state = make_state()
    state.active_outfit_id = "missing"
    layers = build_prompt_layers(state, "dataset_0")
    assert layers["outfit"] == "leather tunic"


def test_override_layer_replaces_value() -> None:
    state = make_state()
    layers = build_prompt_layers(
        state, "passport_face", overrides={"composition": "front portrait, head and shoulders"}
    )
    assert layers["composition"] == "front portrait, head and shoulders"
    # Expression rule still wins on passport_*.
    assert layers["expression"] == "neutral"


def test_override_expression_honoured_only_outside_passport_and_emotion() -> None:
    state = make_state()
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "grim, brooding"

    dataset_layers = build_prompt_layers(state, "dataset_0", overrides={"expression": "laughing"})
    assert dataset_layers["expression"] == "laughing"

    passport_layers = build_prompt_layers(
        state, "passport_face", overrides={"expression": "laughing"}
    )
    assert passport_layers["expression"] == "neutral"


def test_unknown_override_raises() -> None:
    state = make_state()
    with pytest.raises(ValueError, match="unknown prompt layer override keys"):
        build_prompt_layers(state, "passport_face", overrides={"bogus": "x"})


def test_render_prompt_text_drops_empty_layers_and_keeps_order() -> None:
    layers = {
        "style": "grim comic",
        "face": "",
        "body": "stocky",
        "outfit": "tunic",
        "expression": "neutral",
        "composition": "",
    }
    text = render_prompt_text(layers)
    assert text.startswith("[STYLE]\ngrim comic")
    assert "[FACE]" not in text
    assert "[BODY]\nstocky" in text
    # OUTFIT appears before EXPRESSION.
    assert text.index("[OUTFIT]") < text.index("[EXPRESSION]")


def test_layer_names_constant_matches_canonical_order() -> None:
    assert LAYER_NAMES == ("style", "face", "body", "outfit", "expression", "composition")


def test_to_prompt_layers_round_trip() -> None:
    layers = {
        "style": "grim",
        "face": "broad",
        "body": "stocky",
        "outfit": "tunic",
        "expression": "neutral",
        "composition": "portrait",
    }
    pl = to_prompt_layers(layers)
    assert pl.style == "grim"
    assert pl.composition == "portrait"
