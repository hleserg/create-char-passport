"""Canonical COMPOSITION scene registry + per-character overrides.

A *scene* is a named COMPOSITION-layer preset — the camera / framing /
background text that varies per frame. The five passport frames plus the
complex-outfit profile shot have fixed, hand-tuned prompts (the "Реестр
готовых промтов [COMPOSITION]" of ``plan/proekt_zametki.md`` §5). Those are
the *hardcode*.

A user may, as a last resort, override a scene's prompt for one character —
to strip an unwanted artefact or nudge the camera/model for a specific frame.
The override is persisted on the character (``state.scene_overrides``) and is
then used for **every future generation of that scene for that character**,
replacing the registry hardcode for that one preset. Other scenes and other
characters are untouched.

This module is the model/data foundation for that feature: the registry, the
``step_key → scene`` mapping, and the override resolver. The visible "Edit
scene" button + warning dialog live on the generation screens (HLE-728/730)
and consume :func:`build_step_overrides` / :func:`set_scene_override`.

# PLAYBOOK-START
# id: registry-default-with-persisted-override
# title: Hardcoded default registry + persisted per-entity override
# status: draft
# category: configuration
# tags: [overrides, persistence, defaults]
# Keep canonical defaults in a code-level registry, and let a single entity
# override one entry in its own persisted state. The resolver reads the
# override if present else the registry default; writing a value equal to the
# default (or blank) clears the override so persisted state only ever holds a
# meaningful deviation. Generalizes to any "ship sane defaults, allow scoped,
# durable customization" surface (feature flags, prompt templates, themes).
# PLAYBOOK-END
"""

from __future__ import annotations

from enum import StrEnum

from create_char_passport.state import CharacterState, StepKind, classify_step


class SceneId(StrEnum):
    """Stable identifier for a COMPOSITION scene preset."""

    FRONT_PORTRAIT = "front_portrait"
    FRONT_FULL = "front_full"
    PROFILE_PORTRAIT = "profile_portrait"
    BACK_FULL = "back_full"
    THREE_QUARTER_FULL = "three_quarter_full"
    PROFILE_FULL = "profile_full"


# Russian labels for the (future) "Edit scene" UI — value is what matters
# downstream, the label is purely a UI hint (cf. the emotion presets).
SCENE_LABELS: dict[str, str] = {
    SceneId.FRONT_PORTRAIT: "Фас-портрет",
    SceneId.FRONT_FULL: "Фас, полный рост",
    SceneId.PROFILE_PORTRAIT: "Профиль-портрет",
    SceneId.BACK_FULL: "Спина, полный рост",
    SceneId.THREE_QUARTER_FULL: "3/4, полный рост",
    SceneId.PROFILE_FULL: "Профиль, полный рост",
}

# Canonical COMPOSITION prompts (from plan/proekt_zametki.md §5). Each is one
# logical paragraph; the model ignores line wrapping. Strict layer separation:
# COMPOSITION carries framing / background / lighting only and deliberately says
# NOTHING about facial expression — that is owned solely by the EXPRESSION layer
# (K3: neutral for passport, the emotion value for emotion frames). A "neutral
# expression" clause here used to leak into emotion frames and dampen them.
SCENE_PRESETS: dict[str, str] = {
    SceneId.FRONT_PORTRAIT: (
        "Front facing portrait, head and shoulders, plain neutral grey background, soft "
        "even lighting, no harsh shadows, no blood, no dramatic "
        "backlight, no text, no speech bubbles, no caption box, no panel border, no frame, "
        "no lettering, just the character on a clean background."
    ),
    SceneId.FRONT_FULL: (
        "Full-length character reference, head-to-toe, the entire body from hair to shoes "
        "fully inside the frame. Standing straight, both feet flat on the ground, legs and "
        "footwear clearly visible, empty space above the head and below the feet. Small "
        "figure in frame, camera pulled far back. Plain neutral grey background, soft even "
        "lighting, arms relaxed at sides, no text, no panel border, "
        "no frame, no lettering."
    ),
    SceneId.PROFILE_PORTRAIT: (
        "Strict side profile, head facing 90 degrees to the side, only one eye visible, "
        "nose and lips seen in silhouette against the background, ear fully visible, head "
        "and shoulders, plain neutral grey background, soft even lighting, no text, no "
        "panel border, no frame, no lettering."
    ),
    SceneId.BACK_FULL: (
        "Full-length character reference seen from behind, back view, head-to-toe, the "
        "entire body from the top of the hair down to the soles of the shoes fully inside "
        "the frame. Back of the head, hairstyle, back, and clothing from behind clearly "
        "visible. Standing straight, both feet flat on the ground, legs and footwear "
        "visible. Clear empty margin above the head and below the feet, full figure framed "
        "with generous headroom and footroom. Small figure in frame, camera pulled far "
        "back, full body wide shot, no cropping, not a close-up, nothing cut off at the "
        "edges. Plain neutral grey background, soft even lighting, arms relaxed at sides, "
        "no text, no panel border, no frame, no lettering."
    ),
    SceneId.THREE_QUARTER_FULL: (
        "Full-length character reference at a three-quarter angle, body turned about 45 "
        "degrees, head-to-toe, the entire body from the top of the hair down to the soles "
        "of the shoes fully inside the frame. Standing straight, both feet flat on the "
        "ground, legs and footwear clearly visible. Clear empty margin above the head and "
        "below the feet, full figure framed with generous headroom and footroom. Small "
        "figure in frame, camera pulled far back, full body wide shot, no cropping, not a "
        "close-up, nothing cut off at the edges. Plain neutral grey background, soft even "
        "lighting, arms relaxed at sides, no text, no panel border, "
        "no frame, no lettering."
    ),
    SceneId.PROFILE_FULL: (
        "Full-length character reference in strict side profile view, the character's "
        "entire body and head turned 90 degrees to the side, facing screen-left, looking "
        "straight ahead in the direction they are facing, NOT toward the camera. Pure "
        "lateral view: only one side of the face is visible, only one eye, one eyebrow and "
        "one ear shown, the bridge and tip of the nose form a clear outline against the "
        "background, the far cheek and far eye are completely hidden behind the head. The "
        "shoulders, hips and feet are also rotated to the side, one shoulder in front of "
        "the other, body in full lateral orientation. Head-to-toe, the entire body from "
        "the top of the hair down to the soles of the shoes fully inside the frame. "
        "Standing straight, both feet flat on the ground, legs and footwear visible. Clear "
        "empty margin above the head and below the feet, full body wide shot, camera "
        "pulled far back, full figure framed with generous headroom and footroom. Plain "
        "neutral grey background, soft even lighting, arms relaxed at "
        "sides, no text, no panel border, no frame, no lettering. Not a three-quarter view, "
        "not facing the camera, face shown completely from the side."
    ),
}

# Single-scene steps → their canonical scene. Steps that emit several scenes
# (outfit) or carry free-form composition (dataset) are absent: callers resolve
# those scenes directly via :func:`effective_composition`.
STEP_SCENE: dict[str, SceneId] = {
    "passport_face": SceneId.FRONT_PORTRAIT,
    "passport_body": SceneId.FRONT_FULL,
    "passport_profile": SceneId.PROFILE_PORTRAIT,
    "passport_back": SceneId.BACK_FULL,
    "passport_3q": SceneId.THREE_QUARTER_FULL,
    "base_emotion": SceneId.FRONT_PORTRAIT,
}


def _require_known(scene_id: str) -> None:
    """Guard: raise ``ValueError`` unless ``scene_id`` is a registered scene."""
    if scene_id not in SCENE_PRESETS:
        msg = f"unknown scene id: {scene_id!r}"
        raise ValueError(msg)


def default_composition(scene_id: str) -> str:
    """Registry (hardcoded) COMPOSITION text for ``scene_id``."""
    _require_known(scene_id)
    return SCENE_PRESETS[scene_id]


def scene_for_step(step_key: str) -> SceneId | None:
    """Scene a single-scene ``step_key`` renders, or ``None``.

    Resolution is two-tier: the fixed ``STEP_SCENE`` map covers the passport
    frames and the base-emotion portrait; emotion-series steps
    (``emotion_<value>``, deliberately absent from the map) are classified to
    the portrait scene. Outfit / prop / dataset steps return ``None`` (multiple
    scenes or free-form composition).

    Raises ``ValueError`` on an unrecognized ``step_key`` — same contract as
    :func:`create_char_passport.state.classify_step` (fail fast on a bad key).
    """
    fixed = STEP_SCENE.get(step_key)
    if fixed is not None:
        return fixed
    if classify_step(step_key) is StepKind.EMOTION:
        return SceneId.FRONT_PORTRAIT
    return None


def effective_composition(state: CharacterState, scene_id: str) -> str:
    """Override for ``scene_id`` if the character set one, else the registry default.

    The stored override is stripped defensively, so a blank / whitespace-only
    value (e.g. from a hand-edited ``state.json``) falls back to the registry
    default rather than emptying the COMPOSITION layer.
    """
    _require_known(scene_id)
    return (state.scene_overrides.get(scene_id) or "").strip() or SCENE_PRESETS[scene_id]


def set_scene_override(state: CharacterState, scene_id: str, text: str) -> None:
    """Persist a per-character COMPOSITION override for ``scene_id``.

    Writing blank text — or text equal to the registry default — clears the
    override, so ``state.scene_overrides`` only ever holds a meaningful
    deviation from the hardcode.
    """
    _require_known(scene_id)
    cleaned = text.strip()
    if not cleaned or cleaned == SCENE_PRESETS[scene_id]:
        state.scene_overrides.pop(scene_id, None)
        return
    state.scene_overrides[scene_id] = cleaned


def clear_scene_override(state: CharacterState, scene_id: str) -> None:
    """Drop the character's override for ``scene_id`` (revert to the registry default)."""
    _require_known(scene_id)
    state.scene_overrides.pop(scene_id, None)


def build_step_overrides(state: CharacterState, step_key: str) -> dict[str, str]:
    """COMPOSITION override dict for ``step_key`` to pass into ``build_prompt_layers``.

    Returns ``{"composition": <effective text>}`` for single-scene steps, or
    an empty dict for steps with no fixed scene (outfit / prop / dataset).
    Keeps contract K3 untouched: the scene resolution happens here, the prompt
    builder just receives a normal ``overrides`` entry.
    """
    scene = scene_for_step(step_key)
    if scene is None:
        return {}
    return {"composition": effective_composition(state, scene)}
