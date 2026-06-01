"""Emotions phase — 3 base emotions + the optional base-emotion portrait (HLE-729, §5).

The optional emotions phase comes first after the passport (when the "Emotions"
block is on). Each emotion is a **portrait** frame (head & shoulders) generated
point-wise: STYLE + FACE + BODY + OUTFIT(base) + EXPRESSION(this emotion) +
COMPOSITION(portrait), with face + body + style references for identity (§3.5).
EXPRESSION and COMPOSITION are resolved by the canonical builders (K3 forces the
series value for ``emotion_<value>`` and the base value for ``base_emotion``;
``build_step_overrides`` injects the FRONT_PORTRAIT scene), so this module only
wires the step keys, the references, and where the resulting ref is stored.

Unlike the passport there is no separate "approve": generating an emotion writes
its reference directly (``emotions.items[].ref`` / ``base_emotion.ref``); the
page-level approve simply moves on, and an incomplete set is allowed.
"""

from __future__ import annotations

from create_char_passport.gen import GenerationResult, build_prompt_layers, build_step_overrides
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    CharacterState,
    CostLedger,
    emotion_step,
)
from create_char_passport.wizard.generation import identity_refs, render_step_image

BASE_EMOTION_DESCRIPTION: str = (
    "Базовая эмоция — мимика персонажа по умолчанию: подставляется ВМЕСТО neutral во "
    "всех дальнейших генерациях (наряды, предметы, датасет) и при обучении LoRA."
)
BASE_EMOTION_HINT: str = (
    "Короткое выражение по-английски (как в пресетах). НЕ описывай сюда одежду, позу "
    "или фон — это другие слои."
)


def emotion_values(state: CharacterState) -> list[str]:
    """The character's emotion-series values, in order (default: the 3 base emotions)."""
    return [item.value for item in state.emotions.items]


def _render(
    state: CharacterState, step_key: str, *, meter: CostLedger | None, model: str | None
) -> tuple[GenerationResult, str | None]:
    """Build the portrait layers for ``step_key`` and render it with identity refs."""
    layers = build_prompt_layers(state, step_key, overrides=build_step_overrides(state, step_key))
    return render_step_image(
        state, step_key, layers, identity_refs(state), meter=meter, model=model
    )


def generate_emotion(
    state: CharacterState, index: int, *, meter: CostLedger | None = None, model: str | None = None
) -> GenerationResult:
    """Generate the portrait for emotion ``index`` and store its ref on success.

    Point-wise: only this emotion's reference is produced / replaced. Raises
    ``IndexError`` for an out-of-range index.
    """
    items = state.emotions.items
    if not 0 <= index < len(items):
        msg = f"emotion index out of range: {index}"
        raise IndexError(msg)
    item = items[index]
    result, relative = _render(state, emotion_step(item.value), meter=meter, model=model)
    if result.ok:
        item.ref = relative
    return result


def generate_base_emotion(
    state: CharacterState, *, meter: CostLedger | None = None, model: str | None = None
) -> GenerationResult:
    """Generate the base-emotion portrait (EXPRESSION = base value) and store its ref."""
    result, relative = _render(state, BASE_EMOTION_STEP, meter=meter, model=model)
    if result.ok:
        state.emotions.base_emotion.ref = relative
    return result


def missing_emotion_refs(state: CharacterState) -> list[str]:
    """Emotion labels still without a generated ref — drives the approve dialog.

    Includes the base emotion only when its block is enabled but ungenerated.
    """
    missing = [item.value for item in state.emotions.items if not item.ref]
    base = state.emotions.base_emotion
    if base.enabled and not base.ref:
        missing.append("базовая эмоция")
    return missing
