"""Event logic for the input screens — pure session mutators, no Gradio.

Each handler takes the per-session :class:`WizardSession` (plus the raw input
values a Gradio event would hand it), mutates the session / its character, and
persists ``state.json`` after every significant action (§6 rule). They return
the session so a ``gr.State`` can pick up the change; the Gradio glue in
:mod:`create_char_passport.screens.views` turns the resulting session into
component updates.

Keeping these Gradio-free means the whole start -> style -> char-data flow is
unit-tested by direct calls; the only thing left to the (test-covered)
``build_demo`` wiring is plumbing inputs to outputs.
"""

from __future__ import annotations

from create_char_passport.gen import clear_scene_override, set_scene_override
from create_char_passport.screens.router import (
    ScreenId,
    WizardSession,
    next_screen,
    previous_screen,
    resume_screen,
)
from create_char_passport.state import CharacterState, CostLedger
from create_char_passport.storage import save_state
from create_char_passport.wizard.extraction import ExtractedCharacter, extract_characters
from create_char_passport.wizard.forms import apply_table as _apply_table
from create_char_passport.wizard.forms import (
    character_from_extracted,
    set_base_emotion,
    set_emotions_enabled,
    set_outfits_enabled,
    set_props_enabled,
    sync_outfits,
    sync_props,
)
from create_char_passport.wizard.style import apply_style, draft_style_prompt


def _persist(session: WizardSession) -> None:
    """Save the session's character to the bucket, if there is one."""
    if session.character is not None:
        save_state(session.character)


def _attribute_cost(session: WizardSession, meter: CostLedger) -> None:
    """Bill a *character-specific* action to the session total + active character.

    Use this only for calls made on behalf of the active character (e.g. style
    drafting): the spend lands on both the session running total and the
    character's persisted ledger (so it survives a reopen). Cross-character /
    pre-character calls like extraction must NOT use this — they belong to the
    session only (see :func:`on_extract`); otherwise an incidentally-loaded
    character would be wrongly billed. A spend-free meter is a cheap no-op.
    """
    session.cost.merge(meter)
    if session.character is not None:
        session.character.cost.merge(meter)
        _persist(session)


# --------------------------------------------------------------------------- #
# Start screen
# --------------------------------------------------------------------------- #
def on_extract(session: WizardSession, text: str) -> WizardSession:
    """Run the paid extraction call and stash the results on the session."""
    meter = CostLedger()
    session.extracted_characters = list(extract_characters(text or "", meter=meter))
    # Extraction is a cross-character call — bill the session only, never an
    # incidentally-loaded character (would inflate its persisted ledger).
    session.cost.merge(meter)
    count = len(session.extracted_characters)
    session.notice = (
        f"Extracted {count} character(s)."
        if count
        else "No characters extracted — paste more text or add one by hand."
    )
    return session


def _find_extracted(session: WizardSession, name: str) -> ExtractedCharacter | None:
    for candidate in session.extracted_characters:
        if isinstance(candidate, ExtractedCharacter) and candidate.name == name:
            return candidate
    return None


def on_pick_extracted(session: WizardSession, name: str) -> WizardSession:
    """Open the data screen for a picked extracted character (style step first)."""
    extracted = _find_extracted(session, name)
    if extracted is None:
        return session
    session.character = character_from_extracted(extracted, style_prompt=session.style_prompt)
    if session.style_approved:
        session.current_screen = ScreenId.CHAR_DATA
        _persist(session)
    else:
        session.current_screen = ScreenId.STYLE
    session.notice = ""
    return session


def on_open_saved(session: WizardSession, character_id: str) -> WizardSession:
    """Load a saved character from the bucket and resume on the right screen."""
    loaded = open_saved_character(character_id)
    if loaded is None:
        session.notice = f"Could not open '{character_id}'."
        return session
    state, screen = loaded
    session.character = state
    style = state.prompt_layers.style.strip()
    if style:
        session.style_approved = True
        session.style_prompt = style
    session.current_screen = screen
    session.notice = ""
    return session


def open_saved_character(character_id: str) -> tuple[CharacterState, ScreenId] | None:
    """Load ``character_id`` from the bucket and pick its resume screen (§5).

    Returns ``(state, screen)`` — ``CHAR_DATA`` when the pipeline finished
    (``current_step`` empty) else the screen owning the saved step. ``None``
    when no saved state exists.
    """
    from create_char_passport.storage import load_state

    state = load_state(character_id)
    if state is None:
        return None
    return state, resume_screen(state)


# --------------------------------------------------------------------------- #
# Style screen
# --------------------------------------------------------------------------- #
def on_draft_style(
    session: WizardSession, image_paths: list[str] | None
) -> tuple[WizardSession, str]:
    """Draft a STYLE prompt from reference photos (paid multimodal call) + bill it.

    Returns ``(session, draft_text)`` so the running cost (attributed to the
    active character + session total) rides back into ``gr.State`` alongside
    the drafted prompt.
    """
    meter = CostLedger()
    draft = draft_style_prompt(list(image_paths or []), meter=meter)
    _attribute_cost(session, meter)
    return session, draft


def on_approve_style(session: WizardSession, style_text: str) -> WizardSession:
    """Freeze STYLE for the session and stamp it onto the current character."""
    session.style_prompt = (style_text or "").strip()
    session.style_approved = True
    if session.character is not None:
        apply_style(session.character, session.style_prompt)
        session.current_screen = ScreenId.CHAR_DATA
        _persist(session)
    else:
        session.current_screen = ScreenId.HOME
    return session


# --------------------------------------------------------------------------- #
# Character-data screen
# --------------------------------------------------------------------------- #
def on_update_table(session: WizardSession, table: dict[str, str]) -> WizardSession:
    """Write edited trait-table values back onto the character."""
    if session.character is not None:
        _apply_table(session.character, table)
        _persist(session)
    return session


def on_toggle_emotions(session: WizardSession, enabled: bool) -> WizardSession:
    """Toggle the emotions block (nested ``emotions.enabled``)."""
    if session.character is not None:
        set_emotions_enabled(session.character, enabled)
        _persist(session)
    return session


def on_update_base_emotion(session: WizardSession, enabled: bool, value: str) -> WizardSession:
    """Store the base-emotion toggle + value."""
    if session.character is not None:
        set_base_emotion(session.character, enabled, value or "")
        _persist(session)
    return session


def on_toggle_outfits(session: WizardSession, enabled: bool) -> WizardSession:
    """Toggle the additional-outfits block."""
    if session.character is not None:
        set_outfits_enabled(session.character, enabled)
        _persist(session)
    return session


def on_update_outfits(session: WizardSession, rows: object) -> WizardSession:
    """Rebuild the outfit rows from the edited dataframe."""
    if session.character is not None:
        sync_outfits(session.character, _rows(rows))
        _persist(session)
    return session


def on_toggle_props(session: WizardSession, enabled: bool) -> WizardSession:
    """Toggle the props block."""
    if session.character is not None:
        set_props_enabled(session.character, enabled)
        _persist(session)
    return session


def on_update_props(session: WizardSession, rows: object) -> WizardSession:
    """Rebuild the prop rows from the edited dataframe."""
    if session.character is not None:
        sync_props(session.character, _rows(rows))
        _persist(session)
    return session


# --------------------------------------------------------------------------- #
# Scene editing (COMPOSITION override) — consumed by the generation screens
# once they exist (HLE-728/730). The override persists per character: the new
# prompt replaces the scene's hardcode for every future generation of it.
# --------------------------------------------------------------------------- #
def on_set_scene_override(session: WizardSession, scene_id: str, text: str) -> WizardSession:
    """Store a custom COMPOSITION prompt for one scene and persist it."""
    if session.character is not None:
        set_scene_override(session.character, scene_id, text or "")
        _persist(session)
    return session


def on_clear_scene_override(session: WizardSession, scene_id: str) -> WizardSession:
    """Revert a scene to its registry default and persist."""
    if session.character is not None:
        clear_scene_override(session.character, scene_id)
        _persist(session)
    return session


def on_next(session: WizardSession) -> WizardSession:
    """Advance to the next enabled screen (e.g. char-data -> passport)."""
    session.current_screen = next_screen(session)
    _persist(session)
    return session


def on_back(session: WizardSession) -> WizardSession:
    """Step back to the previous enabled screen."""
    session.current_screen = previous_screen(session)
    return session


def _rows(rows: object) -> list[list[object]]:
    """Coerce a Gradio dataframe value (list of rows, or ``{"data": [...]}``)."""
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list):
        return []
    return [list(r) for r in rows]
