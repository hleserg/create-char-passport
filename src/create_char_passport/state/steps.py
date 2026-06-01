"""Step-key vocabulary — contract K1.

Every wizard step has a stable string identifier used as a key in
``state.steps{}``, ``current_step``, the ``&step&`` markers of the
"Edit-with-AI" reply parser, and the ``need_regen`` gate.

The vocabulary mixes static keys (passports + base emotion) with parametric
ones (emotion / outfit / prop / dataset). Dynamic-key constructors live here
so the rest of the codebase never builds keys by hand.
"""

from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from create_char_passport.state.schema import CharacterState

PASSPORT_STEPS: tuple[str, ...] = (
    "passport_face",
    "passport_body",
    "passport_profile",
    "passport_back",
    "passport_3q",
)

BASE_EMOTION_STEP: str = "base_emotion"

EMOTION_PREFIX: str = "emotion_"
OUTFIT_PREFIX: str = "outfit_"
PROP_PREFIX: str = "prop_"
DATASET_PREFIX: str = "dataset_"

ALL_STATIC_STEPS: tuple[str, ...] = (*PASSPORT_STEPS, BASE_EMOTION_STEP)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_OUTFIT_DETAIL_RE = re.compile(r"_detail_\d+$")


class StepKind(StrEnum):
    """Coarse step category, derived from the key prefix."""

    PASSPORT = "passport"
    BASE_EMOTION = "base_emotion"
    EMOTION = "emotion"
    OUTFIT = "outfit"
    OUTFIT_DETAIL = "outfit_detail"
    PROP = "prop"
    DATASET = "dataset"


def slugify(value: str) -> str:
    """Lower-case ASCII slug, ``a-z0-9_`` only, used for emotion suffixes."""
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_RE.sub("_", normalized.lower()).strip("_")
    return slug or "x"


def emotion_step(value: str) -> str:
    """Build ``emotion_<slug>`` from a free-form emotion label."""
    return f"{EMOTION_PREFIX}{slugify(value)}"


def outfit_step(outfit_id: str) -> str:
    """Build ``outfit_<id>`` from the outfit's stored id."""
    return f"{OUTFIT_PREFIX}{outfit_id}"


def outfit_detail_step(outfit_id: str, n: int) -> str:
    """Build ``outfit_<id>_detail_<n>`` for a costume close-up shot."""
    return f"{OUTFIT_PREFIX}{outfit_id}_detail_{n}"


def prop_shot_step(prop_id: str, n: int) -> str:
    """Build ``prop_<id>_shot_<n>`` for one frame of a prop."""
    return f"{PROP_PREFIX}{prop_id}_shot_{n}"


def dataset_step(idx: int) -> str:
    """Build ``dataset_<idx>`` for one composition in the dataset array."""
    return f"{DATASET_PREFIX}{idx}"


def is_passport_step(step_key: str) -> bool:
    """True if the key names one of the 5 mandatory passport frames."""
    return step_key in PASSPORT_STEPS


def classify_step(step_key: str) -> StepKind:
    """Bucket a step_key into a ``StepKind``.

    Outfit-detail keys (``outfit_<id>_detail_<n>``) are detected by the
    ``_detail_`` infix; plain outfit keys fall back to ``OUTFIT``.
    """
    if step_key in PASSPORT_STEPS:
        return StepKind.PASSPORT
    if step_key == BASE_EMOTION_STEP:
        return StepKind.BASE_EMOTION
    if step_key.startswith(EMOTION_PREFIX):
        return StepKind.EMOTION
    if step_key.startswith(OUTFIT_PREFIX):
        # Tail-anchored ``_detail_<int>`` only — substring would misclassify
        # outfit ids that happen to contain ``_detail_`` (and collide with a
        # detail key on those ids).
        return StepKind.OUTFIT_DETAIL if _OUTFIT_DETAIL_RE.search(step_key) else StepKind.OUTFIT
    if step_key.startswith(PROP_PREFIX):
        return StepKind.PROP
    if step_key.startswith(DATASET_PREFIX):
        return StepKind.DATASET
    msg = f"unknown step_key: {step_key!r}"
    raise ValueError(msg)


def ordered_step_keys(state: CharacterState) -> list[str]:
    """Return every step_key that *could* exist for this state, in pipe order.

    Order follows the wizard flow: 5 passport frames → base emotion → emotion
    series → outfit + details → props → dataset compositions. Optional blocks
    contribute keys only when their feature flag is on; dynamic suffixes are
    enumerated from the state's own arrays (so suffix order is deterministic
    per save, not lexical).
    """
    keys: list[str] = list(PASSPORT_STEPS)
    if state.emotions.enabled or state.emotions.base_emotion.enabled:
        keys.append(BASE_EMOTION_STEP)
    if state.emotions.enabled:
        keys.extend(emotion_step(item.value) for item in state.emotions.items)
    if state.outfits_enabled:
        for outfit in state.outfits:
            keys.append(outfit_step(outfit.id))
            keys.extend(outfit_detail_step(outfit.id, n) for n in range(1, len(outfit.details) + 1))
    if state.props_enabled:
        for prop in state.props:
            keys.extend(prop_shot_step(prop.id, n) for n in range(1, len(prop.shots) + 1))
    keys.extend(dataset_step(i) for i in range(len(state.dataset_compositions)))
    return keys
