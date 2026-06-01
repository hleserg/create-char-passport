"""Tests for the screen router (pure logic, no Gradio)."""

from __future__ import annotations

from create_char_passport.screens import (
    SCREEN_ORDER,
    ScreenId,
    WizardSession,
    can_advance,
    next_screen,
    pending_regen_step,
    previous_screen,
    resume_screen,
)
from create_char_passport.state import (
    EmotionItem,
    OutfitEntry,
    PromptLayers,
    PropEntry,
    StepRecord,
    blank_state,
)


def test_home_advances_to_style_then_char_data() -> None:
    session = WizardSession(current_screen=ScreenId.HOME)
    assert next_screen(session) is ScreenId.STYLE
    session.current_screen = ScreenId.STYLE
    assert next_screen(session) is ScreenId.CHAR_DATA


def test_optional_phases_skipped_when_flags_off() -> None:
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=blank_state("Heron"))
    # Emotions/outfits/props off → straight to dataset after passport.
    assert next_screen(session) is ScreenId.DATASET


def test_optional_phases_visited_when_flags_on() -> None:
    state = blank_state("Heron")
    state.emotions.enabled = True
    state.outfits_enabled = True
    state.props_enabled = True
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    assert next_screen(session) is ScreenId.EMOTIONS
    session.current_screen = ScreenId.EMOTIONS
    assert next_screen(session) is ScreenId.OUTFITS
    session.current_screen = ScreenId.OUTFITS
    assert next_screen(session) is ScreenId.PROPS
    session.current_screen = ScreenId.PROPS
    assert next_screen(session) is ScreenId.DATASET


def test_emotions_screen_active_when_only_base_emotion_toggle_on() -> None:
    state = blank_state("Heron")
    state.emotions.base_emotion.enabled = True
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    assert next_screen(session) is ScreenId.EMOTIONS


def test_previous_screen_skips_disabled_phases() -> None:
    session = WizardSession(current_screen=ScreenId.DATASET, character=blank_state("Heron"))
    assert previous_screen(session) is ScreenId.PASSPORT


def test_previous_screen_clamps_to_home() -> None:
    session = WizardSession(current_screen=ScreenId.HOME)
    assert previous_screen(session) is ScreenId.HOME


def test_next_screen_clamps_to_finish() -> None:
    session = WizardSession(current_screen=ScreenId.FINISH, character=blank_state("Heron"))
    assert next_screen(session) is ScreenId.FINISH


def test_pending_regen_step_picks_earliest() -> None:
    state = blank_state("Heron")
    state.steps["passport_body"] = StepRecord(need_regen=True)
    state.steps["passport_face"] = StepRecord(need_regen=True)
    assert pending_regen_step(state) == "passport_face"


def test_pending_regen_step_none_when_clean() -> None:
    state = blank_state("Heron")
    state.steps["passport_face"] = StepRecord(need_regen=False)
    assert pending_regen_step(state) is None


def test_can_advance_requires_character_after_home() -> None:
    session = WizardSession(current_screen=ScreenId.HOME)
    assert can_advance(session) is True


def test_can_advance_false_when_next_step_unfilled() -> None:
    state = blank_state("Heron")
    session = WizardSession(current_screen=ScreenId.CHAR_DATA, character=state)
    # passport_face step not yet generated → cannot advance into PASSPORT.
    assert can_advance(session) is False


def test_can_advance_true_when_next_step_filled() -> None:
    state = blank_state("Heron")
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png",
        prompt_layers=PromptLayers(face="broad nose"),
    )
    session = WizardSession(current_screen=ScreenId.CHAR_DATA, character=state)
    assert can_advance(session) is True


def test_can_advance_false_when_pending_regen() -> None:
    state = blank_state("Heron")
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png",
        prompt_layers=PromptLayers(face="broad nose"),
        need_regen=True,
    )
    session = WizardSession(current_screen=ScreenId.CHAR_DATA, character=state)
    assert can_advance(session) is False


def test_can_advance_into_emotions_requires_first_emotion_step() -> None:
    state = blank_state("Heron")
    state.emotions.enabled = True
    state.emotions.items = [EmotionItem(value="neutral")]
    state.emotions.base_emotion.enabled = True
    state.steps["base_emotion"] = StepRecord(
        last_path="refs/base.png", prompt_layers=PromptLayers(expression="grim")
    )
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    assert can_advance(session) is True


def test_can_advance_for_outfits_props_dataset_uses_representative_step() -> None:
    state = blank_state("Heron")
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="armor")]
    state.props_enabled = True
    state.props = [PropEntry(id="sword")]
    state.dataset_compositions = ["walking"]

    state.steps["outfit_armor"] = StepRecord(
        last_path="refs/outfit_armor.png", prompt_layers=PromptLayers(outfit="armor")
    )
    state.steps["prop_sword_shot_1"] = StepRecord(
        last_path="refs/sword.png", prompt_layers=PromptLayers(composition="closeup")
    )
    state.steps["dataset_0"] = StepRecord(
        last_path="refs/walk.png", prompt_layers=PromptLayers(composition="walking")
    )

    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    assert can_advance(session) is True


def test_can_advance_outfits_when_no_outfit_defined_is_false() -> None:
    state = blank_state("Heron")
    state.outfits_enabled = True  # block toggle on but no rows added yet
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    assert can_advance(session) is False


def test_resume_screen_when_current_step_empty_goes_to_char_data() -> None:
    state = blank_state("Heron")
    assert resume_screen(state) is ScreenId.CHAR_DATA


def test_resume_screen_routes_each_step_prefix() -> None:
    state = blank_state("Heron")
    state.current_step = "passport_body"
    assert resume_screen(state) is ScreenId.PASSPORT
    state.current_step = "base_emotion"
    assert resume_screen(state) is ScreenId.EMOTIONS
    state.current_step = "emotion_neutral"
    assert resume_screen(state) is ScreenId.EMOTIONS
    state.current_step = "outfit_armor"
    assert resume_screen(state) is ScreenId.OUTFITS
    state.current_step = "prop_sword_shot_1"
    assert resume_screen(state) is ScreenId.PROPS
    state.current_step = "dataset_0"
    assert resume_screen(state) is ScreenId.DATASET
    state.current_step = "what_is_this"
    assert resume_screen(state) is ScreenId.CHAR_DATA


def test_screen_order_starts_at_home_and_ends_at_finish() -> None:
    assert SCREEN_ORDER[0] is ScreenId.HOME
    assert SCREEN_ORDER[-1] is ScreenId.FINISH
