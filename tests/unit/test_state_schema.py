"""Tests for state dataclass schema + (de)serialization."""

from __future__ import annotations

from create_char_passport.state import (
    BaseEmotion,
    BaseOutfit,
    EmotionItem,
    Emotions,
    OutfitDetail,
    OutfitEntry,
    OutfitRefs,
    PromptLayers,
    PropEntry,
    PropShot,
    StepRecord,
    blank_state,
    character_id_from_name,
    state_from_dict,
    state_to_dict,
)


def test_character_id_from_name_slugifies() -> None:
    assert character_id_from_name("Heron the Strong") == "heron-the-strong"
    assert character_id_from_name("   ") == "character"
    assert character_id_from_name("Übermensch!") == "ubermensch"


def test_blank_state_defaults() -> None:
    state = blank_state("Heron")
    assert state.character_id == "heron"
    assert state.name == "Heron"
    assert state.active_outfit_id == "base"
    assert state.current_step is None
    assert state.emotions.enabled is False
    # Non-neutral expression series pre-seeded ("neutral" lives in the passport).
    assert [item.value for item in state.emotions.items] == [
        "angry, furious",
        "smiling warmly",
    ]


def test_blank_state_explicit_character_id() -> None:
    state = blank_state("Heron", character_id="hero-001")
    assert state.character_id == "hero-001"


def test_round_trip_full_state() -> None:
    state = blank_state("Tyra")
    state.character_table = {"sex": "female", "age": "30"}
    state.emotions = make_full_emotions()
    state.base_outfit = BaseOutfit(prompt="leather tunic", frozen=True, ref="refs/base.png")
    state.outfits_enabled = True
    state.outfits = [
        OutfitEntry(
            id="armor",
            prompt="lamellar armor",
            complex=True,
            refs=OutfitRefs(front_full="refs/of.png", front_full_approved=True),
            details=[OutfitDetail(prompt="pauldron", ref="refs/pauldron.png")],
        )
    ]
    state.props_enabled = True
    state.props = [
        PropEntry(id="sword", name="iron sword", shots=[PropShot(what="hilt", prompt="closeup")])
    ]
    state.prompt_layers = PromptLayers(style="grim comic", face="broad nose")
    state.steps = {
        "passport_face": StepRecord(
            last_path="refs/passport_face.png",
            approved_path="refs/passport_face.png",
            prompt_layers=PromptLayers(face="broad nose"),
            need_regen=False,
        )
    }
    state.current_step = "passport_face"
    state.dataset_compositions = ["walking", "sitting"]

    blob = state_to_dict(state)
    restored = state_from_dict(blob)

    assert restored.character_id == "tyra"
    assert restored.character_table == {"sex": "female", "age": "30"}
    assert restored.emotions.enabled is True
    assert restored.outfits[0].complex is True
    # The per-scene approved flags survive the round-trip (front True, back default).
    assert restored.outfits[0].refs.front_full_approved is True
    assert restored.outfits[0].refs.back_full_approved is False
    assert restored.outfits[0].details[0].prompt == "pauldron"
    assert restored.props[0].shots[0].what == "hilt"
    assert restored.prompt_layers.style == "grim comic"
    assert restored.steps["passport_face"].approved_path == "refs/passport_face.png"
    assert restored.steps["passport_face"].prompt_layers.face == "broad nose"
    assert restored.current_step == "passport_face"
    assert restored.dataset_compositions == ["walking", "sitting"]


def make_full_emotions() -> Emotions:
    emotions = Emotions(enabled=True)
    emotions.items = [EmotionItem(value="neutral", ref="refs/neutral.png")]
    emotions.base_emotion = BaseEmotion(enabled=True, value="grim, brooding", ref=None)
    return emotions


def test_outfit_refs_approved_defaults_false_for_legacy_state() -> None:
    # A saved outfit from before the approved flags existed loads them as False
    # (proves _outfit_entry parses the new keys, not silently drops them).
    restored = state_from_dict(
        {"character_id": "x", "outfits": [{"id": "1", "refs": {"front_full": "a.png"}}]}
    )
    refs = restored.outfits[0].refs
    assert refs.front_full == "a.png"
    assert refs.front_full_approved is False
    assert refs.back_full_approved is False
    assert refs.profile_full_approved is False


def test_state_from_dict_tolerates_missing_optional_blocks() -> None:
    minimal = {"character_id": "x"}
    restored = state_from_dict(minimal)
    assert restored.name == ""
    assert restored.character_table == {}
    assert restored.emotions.items  # default series still seeded
    assert restored.outfits == []
    assert restored.props == []
    assert restored.steps == {}
    assert restored.current_step is None
