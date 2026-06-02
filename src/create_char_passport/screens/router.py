"""Pure routing logic — no Gradio imports.

The wizard navigates a fixed sequence of screens. Optional phases (emotions
/ outfits / props) are skipped when their feature flag is off. The router
exposes:

* :func:`next_screen` / :func:`previous_screen` — linear move.
* :func:`can_advance` — Forward button enabled iff the next step's state is
  already filled in (matches §5 "Buttons" rule from ``plan/proekt_zametki.md``).
* :func:`pending_regen_step` — gate that jumps to the earliest step flagged
  ``need_regen=True`` before any forward move.
* :func:`resume_screen` — what to open when the user clicks a saved character
  on the home screen (matches §5 "Resume" rule).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from create_char_passport.state import CharacterState, CostLedger, ordered_step_keys


class ScreenId(StrEnum):
    """Identifier for each wizard screen; values are stable strings."""

    HOME = "home"
    STYLE = "style"
    CHAR_DATA = "char_data"
    PASSPORT = "passport"
    EMOTIONS = "emotions"
    OUTFITS = "outfits"
    PROPS = "props"
    DATASET = "dataset"
    FINISH = "finish"


SCREEN_ORDER: tuple[ScreenId, ...] = (
    ScreenId.HOME,
    ScreenId.STYLE,
    ScreenId.CHAR_DATA,
    ScreenId.PASSPORT,
    ScreenId.EMOTIONS,
    ScreenId.OUTFITS,
    ScreenId.PROPS,
    ScreenId.DATASET,
    ScreenId.FINISH,
)

_OPTIONAL_FLAG: dict[ScreenId, str] = {
    ScreenId.EMOTIONS: "emotions_enabled",
    ScreenId.OUTFITS: "outfits_enabled",
    ScreenId.PROPS: "props_enabled",
}


@dataclass(slots=True)
class WizardSession:
    """Per-session wizard state held in ``gr.State``.

    The session zeroes when the user opens the app fresh; it gets a
    ``character`` once they pick a name (extracted or saved). The
    ``current_screen`` tracks navigation independently of
    ``character.current_step`` (the latter is persisted; the former is
    transient).
    """

    current_screen: ScreenId = ScreenId.HOME
    character: CharacterState | None = None
    style_approved: bool = False
    style_prompt: str = ""
    # Stable path to the approved STYLE reference image (a persisted copy), so a
    # second character picked in the same session also gets the style ref attached.
    style_image_path: str = ""
    # Transient UI flag: the emotions phase offers a "skip with an incomplete set"
    # button after Approve finds ungenerated emotions (the phase allows it, §5).
    emotions_offer_skip: bool = False
    # Transient UI flag: ``(outfit_index, detail_n)`` whose delete needs a confirm
    # (the costume detail already has a generation, §5); ``None`` when no pending
    # delete. Cleared on confirm or any other outfit action.
    outfit_pending_delete: tuple[int, int] | None = None
    # Transient UI flag: Approve found a costume detail with a prompt but no
    # generation (§5) — a second Approve proceeds (details persist, nothing lost).
    outfit_pending_approve_confirm: bool = False
    # Transient UI flag: ``(prop_index, shot_n)`` whose delete needs a confirm
    # (the product shot already has a generation, §5); ``None`` when no pending.
    prop_pending_delete: tuple[int, int] | None = None
    notice: str = ""
    # Running API spend for the whole session (incl. pre-character calls like
    # extraction); the per-character figure lives on ``character.cost``.
    cost: CostLedger = field(default_factory=CostLedger)
    available_character_ids: list[str] = field(default_factory=list)
    # Characters extracted from the pasted text, awaiting the user's pick.
    # Typed ``Any`` to avoid a router -> wizard import cycle; holds
    # ``wizard.ExtractedCharacter`` instances.
    extracted_characters: list[Any] = field(default_factory=list)


def _flag_for_optional(screen: ScreenId, session: WizardSession) -> bool:
    """True if an optional screen's feature flag is on (always-on for non-optional)."""
    field_name = _OPTIONAL_FLAG.get(screen)
    if field_name is None:
        return True
    char = session.character
    if char is None:
        return False
    if field_name == "emotions_enabled":
        # The emotions screen renders when the block OR base-emotion toggle is on.
        return char.emotions.enabled or char.emotions.base_emotion.enabled
    return bool(getattr(char, field_name))


def _step_through(start: ScreenId, session: WizardSession, *, direction: int) -> ScreenId:
    """Move ``direction`` (±1) steps along ``SCREEN_ORDER`` skipping disabled screens."""
    idx = SCREEN_ORDER.index(start)
    while True:
        idx += direction
        if idx < 0:
            return SCREEN_ORDER[0]
        if idx >= len(SCREEN_ORDER):
            return SCREEN_ORDER[-1]
        candidate = SCREEN_ORDER[idx]
        if _flag_for_optional(candidate, session):
            return candidate


def next_screen(session: WizardSession) -> ScreenId:
    """Next screen after the current one, skipping disabled optional phases."""
    return _step_through(session.current_screen, session, direction=1)


def previous_screen(session: WizardSession) -> ScreenId:
    """Previous screen before the current one (Back button)."""
    return _step_through(session.current_screen, session, direction=-1)


def pending_regen_step(state: CharacterState) -> str | None:
    """Earliest step_key with ``need_regen=True``, or ``None``.

    Iterates in :func:`ordered_step_keys` order so the gate matches the
    visible pipeline order — not lexical order over the dict.
    """
    for key in ordered_step_keys(state):
        record = state.steps.get(key)
        if record is not None and record.need_regen:
            return key
    return None


def can_advance(session: WizardSession) -> bool:
    """Is the Forward button allowed on the current screen?

    Per §5: forward is enabled only if the *next* step has a saved
    generation AND a prompt. On the Home / Style screens we relax this
    so a brand-new wizard can move at all.
    """
    char = session.character
    if char is None:
        # No character yet → only the Home screen makes sense.
        return session.current_screen == ScreenId.HOME
    if pending_regen_step(char) is not None:
        # Gate: must clear the earliest need_regen before stepping forward.
        return False
    next_id = next_screen(session)
    if next_id in (ScreenId.HOME, ScreenId.STYLE, ScreenId.CHAR_DATA, ScreenId.FINISH):
        return True
    next_step_key = _representative_step_key(next_id, char)
    if next_step_key is None:
        return False
    record = char.steps.get(next_step_key)
    if record is None:
        return False
    return bool(record.last_path and any_layer_filled(record.prompt_layers))


def any_layer_filled(layers: object) -> bool:
    """True if any of the six prompt-layer slots has non-blank text."""
    for name in ("style", "face", "body", "outfit", "expression", "composition"):
        value = getattr(layers, name, "") or ""
        if value.strip():
            return True
    return False


def _representative_step_key(screen: ScreenId, state: CharacterState) -> str | None:
    """First step_key produced by ``screen`` (used to decide can_advance)."""
    keys = ordered_step_keys(state)
    if screen is ScreenId.PASSPORT:
        return keys[0] if keys else None
    if screen is ScreenId.EMOTIONS:
        for key in keys:
            if key == "base_emotion" or key.startswith("emotion_"):
                return key
        return None
    if screen is ScreenId.OUTFITS:
        for key in keys:
            if key.startswith("outfit_"):
                return key
        return None
    if screen is ScreenId.PROPS:
        for key in keys:
            if key.startswith("prop_"):
                return key
        return None
    if screen is ScreenId.DATASET:
        for key in keys:
            if key.startswith("dataset_"):
                return key
        return None
    return None


def resume_screen(state: CharacterState) -> ScreenId:
    """Pick the screen to open when a saved character is reloaded.

    Rule from §5: ``current_step`` empty (or null) → wizard was completed
    → open the first character screen. Otherwise jump to whichever screen
    owns the saved step.
    """
    if not state.current_step:
        return ScreenId.CHAR_DATA
    return screen_for_step(state.current_step)


def screen_for_step(step_key: str) -> ScreenId:
    """Screen that owns ``step_key`` (used by resume + the need_regen gate)."""
    if step_key.startswith("passport_"):
        return ScreenId.PASSPORT
    if step_key == "base_emotion" or step_key.startswith("emotion_"):
        return ScreenId.EMOTIONS
    if step_key.startswith("outfit_"):
        return ScreenId.OUTFITS
    if step_key.startswith("prop_"):
        return ScreenId.PROPS
    if step_key.startswith("dataset_"):
        return ScreenId.DATASET
    return ScreenId.CHAR_DATA
