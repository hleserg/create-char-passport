"""Prompt assembly — contract K3.

The canonical six-layer order is ``STYLE → FACE → BODY → OUTFIT → EXPRESSION
→ COMPOSITION``. ``build_prompt_layers`` returns the layered ``dict`` (so
downstream code can decide whether to send one big string or per-layer
parts) and applies the ``EXPRESSION`` resolution rules required by §5/§6:

* ``passport_*`` → ``neutral`` forced (base emotion is ignored — see
  Decision 5 in ``plan/HLE-661-resheniya.md``).
* ``emotion_<value>`` → that series value.
* All other steps → ``base_emotion.value`` if explicitly set, else
  ``neutral`` (the implicit default holds even when the emotion block as
  a whole is disabled).
"""

from __future__ import annotations

from create_char_passport.state import (
    CharacterState,
    PromptLayers,
    StepKind,
    classify_step,
)
from create_char_passport.state.steps import EMOTION_PREFIX

LAYER_NAMES: tuple[str, ...] = (
    "style",
    "face",
    "body",
    "outfit",
    "expression",
    "composition",
)

_NEUTRAL = "neutral"


def _resolve_expression(state: CharacterState, step_key: str) -> str:
    """Apply the K3 EXPRESSION rule for ``step_key``."""
    kind = classify_step(step_key)
    if kind is StepKind.PASSPORT:
        return _NEUTRAL
    if kind is StepKind.EMOTION:
        return step_key[len(EMOTION_PREFIX) :].replace("_", " ").strip() or _NEUTRAL
    base = state.emotions.base_emotion
    if base.enabled and base.value.strip():
        return base.value.strip()
    return _NEUTRAL


def _resolve_outfit(state: CharacterState) -> str:
    """Pick the OUTFIT layer text based on ``active_outfit_id``."""
    if state.active_outfit_id == "base":
        return state.base_outfit.prompt
    for outfit in state.outfits:
        if outfit.id == state.active_outfit_id:
            return outfit.prompt
    return state.base_outfit.prompt


def build_prompt_layers(
    state: CharacterState,
    step_key: str,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the prompt layers for ``step_key``.

    ``overrides`` lets callers swap individual layers (e.g. inject the
    step-specific COMPOSITION template) without touching the persisted
    ``character_state``. Unknown override keys raise ``ValueError`` so a
    typo never silently dropped.
    """
    overrides = overrides or {}
    bad = set(overrides) - set(LAYER_NAMES)
    if bad:
        msg = f"unknown prompt layer override keys: {sorted(bad)}"
        raise ValueError(msg)

    base = state.prompt_layers
    layers: dict[str, str] = {
        "style": base.style,
        "face": base.face,
        "body": base.body,
        "outfit": _resolve_outfit(state),
        "expression": _resolve_expression(state, step_key),
        "composition": base.composition,
    }
    for name, value in overrides.items():
        layers[name] = value

    # K3: EXPRESSION rules must win over any persisted state — re-apply
    # AFTER overrides so an accidental override on a passport_* step is
    # corrected back to neutral.
    layers["expression"] = _resolve_expression(state, step_key)
    if "expression" in overrides:
        # An explicit override is honoured only for non-passport, non-emotion steps.
        kind = classify_step(step_key)
        if kind not in (StepKind.PASSPORT, StepKind.EMOTION):
            layers["expression"] = overrides["expression"]

    return layers


def render_prompt_text(layers: dict[str, str]) -> str:
    """Render layered prompts into a single text block in canonical order.

    Empty layers are dropped so the generator never sees ``[OUTFIT]\\n\\n``.
    """
    blocks: list[str] = []
    for name in LAYER_NAMES:
        value = (layers.get(name) or "").strip()
        if not value:
            continue
        blocks.append(f"[{name.upper()}]\n{value}")
    return "\n\n".join(blocks)


def to_prompt_layers(layers: dict[str, str]) -> PromptLayers:
    """Convert a layer ``dict`` (as returned by :func:`build_prompt_layers`)
    to a :class:`PromptLayers` dataclass — convenience for state snapshots.
    """
    return PromptLayers(
        style=layers.get("style", ""),
        face=layers.get("face", ""),
        body=layers.get("body", ""),
        outfit=layers.get("outfit", ""),
        expression=layers.get("expression", ""),
        composition=layers.get("composition", ""),
    )
