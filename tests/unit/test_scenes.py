"""Tests for the COMPOSITION scene registry + per-character overrides."""

from __future__ import annotations

import pytest

from create_char_passport.gen import build_prompt_layers
from create_char_passport.gen.scenes import (
    SCENE_LABELS,
    SCENE_PRESETS,
    SceneId,
    build_step_overrides,
    clear_scene_override,
    default_composition,
    effective_composition,
    scene_for_step,
    set_scene_override,
)
from create_char_passport.state import blank_state, state_from_dict, state_to_dict


def test_registry_covers_every_scene_id_with_text() -> None:
    assert set(SCENE_PRESETS) == set(SceneId)
    assert set(SCENE_LABELS) == set(SceneId)
    for scene in SceneId:
        assert SCENE_PRESETS[scene].strip()
        assert SCENE_LABELS[scene].strip()


def test_default_composition_returns_preset() -> None:
    assert default_composition(SceneId.FRONT_PORTRAIT) == SCENE_PRESETS[SceneId.FRONT_PORTRAIT]
    assert default_composition("front_full") == SCENE_PRESETS[SceneId.FRONT_FULL]


def test_default_composition_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown scene id"):
        default_composition("no_such_scene")


@pytest.mark.parametrize(
    ("step_key", "expected"),
    [
        ("passport_face", SceneId.FRONT_PORTRAIT),
        ("passport_body", SceneId.FRONT_FULL),
        ("passport_profile", SceneId.PROFILE_PORTRAIT),
        ("passport_back", SceneId.BACK_FULL),
        ("passport_3q", SceneId.THREE_QUARTER_FULL),
        ("base_emotion", SceneId.FRONT_PORTRAIT),
        ("emotion_grim_brooding", SceneId.FRONT_PORTRAIT),
    ],
)
def test_scene_for_step_single_scene_steps(step_key: str, expected: SceneId) -> None:
    assert scene_for_step(step_key) == expected


def test_composition_presets_carry_no_expression() -> None:
    """Layer separation: COMPOSITION must say nothing about facial expression.

    Expression is owned solely by the EXPRESSION layer (K3). A "neutral
    expression" clause in the shared portrait composition used to leak into
    emotion frames and dampen the very emotion the frame exists to capture.
    """
    for scene in SceneId:
        assert "expression" not in SCENE_PRESETS[scene].lower(), scene


@pytest.mark.parametrize(
    "step_key", ["outfit_outfit_1", "outfit_x_detail_1", "prop_p_shot_1", "dataset_0"]
)
def test_scene_for_step_multi_or_free_steps_return_none(step_key: str) -> None:
    assert scene_for_step(step_key) is None


def test_scene_for_step_unknown_raises() -> None:
    # Fail fast on a bad key, mirroring classify_step's contract.
    with pytest.raises(ValueError, match="unknown step_key"):
        scene_for_step("totally_bogus")


def test_effective_composition_falls_back_to_default() -> None:
    state = blank_state("Conan")
    assert effective_composition(state, SceneId.FRONT_FULL) == SCENE_PRESETS[SceneId.FRONT_FULL]


def test_effective_composition_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown scene id"):
        effective_composition(blank_state("Conan"), "ghost")


def test_effective_composition_ignores_whitespace_only_override() -> None:
    # A corrupted / hand-edited blank override must not empty the layer.
    state = blank_state("Conan")
    state.scene_overrides["front_portrait"] = "   "
    assert (
        effective_composition(state, SceneId.FRONT_PORTRAIT)
        == SCENE_PRESETS[SceneId.FRONT_PORTRAIT]
    )


def test_set_scene_override_stores_and_resolves() -> None:
    state = blank_state("Conan")
    set_scene_override(state, SceneId.FRONT_PORTRAIT, "  custom framing, top-down  ")
    assert state.scene_overrides == {"front_portrait": "custom framing, top-down"}
    assert effective_composition(state, SceneId.FRONT_PORTRAIT) == "custom framing, top-down"


def test_set_scene_override_blank_clears() -> None:
    state = blank_state("Conan")
    set_scene_override(state, SceneId.FRONT_PORTRAIT, "custom")
    set_scene_override(state, SceneId.FRONT_PORTRAIT, "   ")
    assert "front_portrait" not in state.scene_overrides
    assert (
        effective_composition(state, SceneId.FRONT_PORTRAIT)
        == SCENE_PRESETS[SceneId.FRONT_PORTRAIT]
    )


def test_set_scene_override_equal_to_default_is_not_persisted() -> None:
    state = blank_state("Conan")
    set_scene_override(state, SceneId.BACK_FULL, SCENE_PRESETS[SceneId.BACK_FULL])
    assert state.scene_overrides == {}


def test_set_scene_override_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown scene id"):
        set_scene_override(blank_state("Conan"), "ghost", "x")


def test_clear_scene_override() -> None:
    state = blank_state("Conan")
    set_scene_override(state, SceneId.PROFILE_FULL, "custom")
    clear_scene_override(state, SceneId.PROFILE_FULL)
    assert state.scene_overrides == {}
    # Clearing an absent scene is a no-op, not an error.
    clear_scene_override(state, SceneId.PROFILE_FULL)


def test_clear_scene_override_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown scene id"):
        clear_scene_override(blank_state("Conan"), "ghost")


def test_build_step_overrides_uses_default_then_override() -> None:
    state = blank_state("Conan")
    assert build_step_overrides(state, "passport_face") == {
        "composition": SCENE_PRESETS[SceneId.FRONT_PORTRAIT]
    }
    set_scene_override(state, SceneId.FRONT_PORTRAIT, "tight crop, eye level")
    assert build_step_overrides(state, "passport_face") == {"composition": "tight crop, eye level"}


def test_build_step_overrides_empty_for_free_steps() -> None:
    state = blank_state("Conan")
    assert build_step_overrides(state, "dataset_0") == {}
    assert build_step_overrides(state, "outfit_outfit_1") == {}


def test_override_flows_into_prompt_builder() -> None:
    """The override reaches the COMPOSITION layer through the K3 builder."""
    state = blank_state("Conan")
    set_scene_override(state, SceneId.FRONT_PORTRAIT, "low angle, dramatic")
    layers = build_prompt_layers(
        state, "passport_face", overrides=build_step_overrides(state, "passport_face")
    )
    assert layers["composition"] == "low angle, dramatic"


def test_scene_overrides_survive_state_round_trip() -> None:
    state = blank_state("Conan")
    set_scene_override(state, SceneId.THREE_QUARTER_FULL, "wider shot")
    restored = state_from_dict(state_to_dict(state))
    assert restored.scene_overrides == {"three_quarter_full": "wider shot"}
    assert effective_composition(restored, SceneId.THREE_QUARTER_FULL) == "wider shot"
