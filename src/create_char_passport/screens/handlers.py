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

from create_char_passport.gen import SceneId, clear_scene_override, set_scene_override
from create_char_passport.screens.router import (
    ScreenId,
    WizardSession,
    next_screen,
    previous_screen,
    resume_screen,
)
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    CharacterState,
    CostLedger,
    emotion_step,
)
from create_char_passport.storage import character_asset, save_state
from create_char_passport.wizard.emotions import (
    generate_base_emotion,
    generate_emotion,
    missing_emotion_refs,
)
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
from create_char_passport.wizard.outfits import (
    add_outfit_detail,
    adjacent_outfit_step,
    approve_outfit,
    current_outfit_index,
    delete_outfit_detail,
    detail_has_generation,
    first_outfit_step,
    generate_outfit_detail,
    generate_outfit_scene,
    required_scenes_present,
    set_outfit_complex,
)
from create_char_passport.wizard.passport import (
    all_passport_approved,
    apply_layer_edit,
    approve_passport_frame,
    current_passport_step,
    first_pending_passport,
    generate_passport_frame,
    next_passport_step,
    previous_passport_step,
)
from create_char_passport.wizard.props import (
    add_prop_shot,
    adjacent_prop_step,
    current_prop_index,
    delete_prop_shot,
    first_prop_step,
    generate_prop_shot,
    shot_has_generation,
)
from create_char_passport.wizard.style import apply_style, draft_style_prompt, set_style_ref


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
    # A second character picked after style was approved still gets the style
    # reference image copied into its own bucket (the text layer rides via prompt).
    if session.style_image_path:
        set_style_ref(session.character, session.style_image_path)
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


def on_approve_style(
    session: WizardSession, style_text: str, image_paths: list[str] | None = None
) -> WizardSession:
    """Freeze STYLE (text + reference image) for the session and stamp it on the character.

    The first uploaded style photo becomes the project STYLE reference *image*
    (``refs/style.png``), attached with role ``style`` to every later generation
    (§3.5 / §4 step 1). Its stable path is kept on the session so characters picked
    later in the same session inherit it too.
    """
    session.style_prompt = (style_text or "").strip()
    session.style_approved = True
    if session.character is not None:
        apply_style(session.character, session.style_prompt)
        first_image = next((p for p in (image_paths or []) if p), None)
        stored = set_style_ref(session.character, first_image) if first_image else None
        if stored:
            session.style_image_path = str(character_asset(session.character.character_id, stored))
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


# --------------------------------------------------------------------------- #
# Passport phase (5 frames on one screen; cursor = ``character.current_step``)
# --------------------------------------------------------------------------- #
def on_enter_passport(session: WizardSession) -> WizardSession:
    """Place the passport cursor on entry, honouring the ``need_regen`` gate.

    No-op unless we are actually on the passport screen with a character, so it
    is safe to chain after any navigation into the phase (Next / resume / Back).
    """
    state = session.character
    if state is not None and session.current_screen is ScreenId.PASSPORT:
        state.current_step = current_passport_step(state)
        session.notice = ""
        _persist(session)
    return session


def on_passport_edit(session: WizardSession, face: str, body: str, outfit: str) -> WizardSession:
    """Persist edited layer text for the current frame (editable layers only)."""
    state = session.character
    if state is not None:
        apply_layer_edit(state, current_passport_step(state), face=face, body=body, outfit=outfit)
        _persist(session)
    return session


def on_passport_generate(
    session: WizardSession, face: str, body: str, outfit: str
) -> WizardSession:
    """Generate (or regenerate) the current frame; bill the paid call; keep the prompt.

    Regenerate is inferred from the frame already having a generation, so the
    single button covers «Сгенерировать»/«Перегенерить». A failed call leaves
    the previous frame and the edited prompt intact (the engine never raises).
    """
    state = session.character
    if state is None:
        return session
    step_key = current_passport_step(state)
    apply_layer_edit(state, step_key, face=face, body=body, outfit=outfit)
    record = state.steps.get(step_key)
    regenerate = record is not None and record.last_path is not None
    meter = CostLedger()
    result = generate_passport_frame(state, step_key, regenerate=regenerate, meter=meter)
    session.notice = (
        "Готово — проверь кадр и нажми «Утвердить»."
        if result.ok
        else (result.error or "Не удалось сгенерировать. Нажми ещё раз — промт сохранён.")
    )
    # Bills the (successful) call to session + character and persists; a failed
    # call's meter is empty, so this is just the persist of the cleared flags.
    _attribute_cost(session, meter)
    return session


def on_passport_approve(session: WizardSession) -> WizardSession:
    """Approve the current frame (freeze rules apply) and advance the cursor."""
    state = session.character
    if state is None:
        return session
    step_key = current_passport_step(state)
    try:
        approve_passport_frame(state, step_key)
    except ValueError:
        session.notice = "Сначала сгенерируйте кадр, потом утверждайте."
        _persist(session)
        return session
    nxt = next_passport_step(step_key)
    if nxt is not None:
        state.current_step = nxt
        session.notice = "Кадр утверждён → следующий кадр."
    elif all_passport_approved(state):
        session.notice = "Все 5 паспортных кадров утверждены — нажми «Вперёд →»."
    else:
        session.notice = "Кадр утверждён."
    _persist(session)
    return session


def on_passport_back(session: WizardSession) -> WizardSession:
    """Step to the previous frame, or leave the phase backwards from frame 1."""
    state = session.character
    if state is None:
        return session
    prev = previous_passport_step(current_passport_step(state))
    if prev is not None:
        state.current_step = prev
        session.notice = ""
    else:
        session.current_screen = previous_screen(session)
    _persist(session)
    return session


def on_passport_forward(session: WizardSession) -> WizardSession:
    """Advance to the next frame, or leave the phase once all 5 are approved.

    The phase-exit gate is enforced here (not the generic router ``can_advance``,
    which checks the *next phase's* first step): all five frames approved and no
    pending ``need_regen`` before moving to the next screen.
    """
    state = session.character
    if state is None:
        return session
    step_key = current_passport_step(state)
    record = state.steps.get(step_key)
    if record is None or not record.approved_path:
        session.notice = "Утвердите текущий кадр, чтобы идти дальше."
        return session
    nxt = next_passport_step(step_key)
    if nxt is not None:
        state.current_step = nxt
        session.notice = ""
        _persist(session)
        return session
    if all_passport_approved(state) and first_pending_passport(state) is None:
        session.current_screen = next_screen(session)
        # NOTE: ``current_step`` is intentionally left on ``passport_3q`` here.
        # The next phases (emotions/outfits/props/dataset) are still stubs, so
        # there is no real next step_key to set, and clearing it would make
        # resume_screen treat the wizard as finished. When those phases land,
        # set current_step to the first step of the next enabled phase so a
        # reopen resumes there rather than back on the passport screen.
        _persist(session)
    else:
        session.notice = "Сначала утвердите все 5 кадров."
    return session


# --------------------------------------------------------------------------- #
# Emotions phase (optional) — a row of 3 point-wise portraits + base emotion
# --------------------------------------------------------------------------- #
def on_enter_emotions(session: WizardSession) -> WizardSession:
    """Mark the emotions phase for resume and reset the skip offer.

    Points ``current_step`` at an in-pipeline step so a reopen resumes here: the
    first series emotion when the "Emotions" block is on, else the base emotion
    (a base-only state has no ``emotion_<value>`` steps). No-op unless we are on
    the emotions screen with a character.
    """
    state = session.character
    if state is not None and session.current_screen is ScreenId.EMOTIONS:
        session.emotions_offer_skip = False
        if state.emotions.enabled and state.emotions.items:
            state.current_step = emotion_step(state.emotions.items[0].value)
        else:
            state.current_step = BASE_EMOTION_STEP
        session.notice = ""
        _persist(session)
    return session


def on_emotion_generate(session: WizardSession, index: int) -> WizardSession:
    """Generate one emotion portrait (point-wise) and bill the paid call."""
    state = session.character
    if state is None:
        return session
    meter = CostLedger()
    try:
        result = generate_emotion(state, index, meter=meter)
    except IndexError:
        return session
    value = state.emotions.items[index].value
    session.notice = (
        f"Готова эмоция «{value}»."
        if result.ok
        else (result.error or "Не удалось сгенерировать. Попробуй ещё раз — промт сохранён.")
    )
    if result.ok and not missing_emotion_refs(state):
        session.emotions_offer_skip = False  # set complete → drop the stale skip affordance
    _attribute_cost(session, meter)
    return session


def on_base_emotion_generate(session: WizardSession) -> WizardSession:
    """Generate the base-emotion portrait (only when the block is enabled)."""
    state = session.character
    if state is None:
        return session
    base = state.emotions.base_emotion
    if not base.enabled:
        session.notice = "Включи базовую эмоцию, чтобы её сгенерировать."
        return session
    if not base.value.strip():
        # Blank value would resolve EXPRESSION to neutral (K3), silently storing a
        # neutral portrait as the base emotion — the one frame that must NOT be neutral.
        session.notice = "Введи выражение базовой эмоции, потом генерируй."
        return session
    meter = CostLedger()
    result = generate_base_emotion(state, meter=meter)
    session.notice = (
        "Базовая эмоция готова."
        if result.ok
        else (result.error or "Не удалось сгенерировать. Попробуй ещё раз — промт сохранён.")
    )
    if result.ok and not missing_emotion_refs(state):
        session.emotions_offer_skip = False  # set complete → drop the stale skip affordance
    _attribute_cost(session, meter)
    return session


def on_emotions_approve(session: WizardSession) -> WizardSession:
    """Leave the emotions phase; an incomplete set offers a "skip" instead (§5)."""
    state = session.character
    if state is None:
        return session
    missing = missing_emotion_refs(state)
    if missing:
        session.emotions_offer_skip = True
        session.notice = (
            "Не сгенерированы: "
            + ", ".join(missing)
            + ". Догенерируй или нажми «Перейти как есть →»."
        )
        return session
    session.emotions_offer_skip = False
    session.current_screen = next_screen(session)
    _persist(session)
    return session


def on_emotions_skip(session: WizardSession) -> WizardSession:
    """Proceed past the emotions phase with an incomplete reference set."""
    state = session.character
    if state is None:
        return session
    session.emotions_offer_skip = False
    session.current_screen = next_screen(session)
    _persist(session)
    return session


def on_emotions_back(session: WizardSession) -> WizardSession:
    """Step back from the emotions phase (to the passport)."""
    session.emotions_offer_skip = False
    session.current_screen = previous_screen(session)
    _persist(session)
    return session


# --------------------------------------------------------------------------- #
# Outfits phase (optional) — one additional outfit at a time (window 5, §5)
# --------------------------------------------------------------------------- #
def _current_outfit(session: WizardSession) -> tuple[CharacterState, int] | None:
    """The character + cursor outfit index, or ``None`` (no character / no outfit)."""
    state = session.character
    if state is None:
        return None
    index = current_outfit_index(state)
    return (state, index) if index is not None else None


def on_enter_outfits(session: WizardSession) -> WizardSession:
    """Mark the outfits phase: cursor → the first outfit, unless already on one.

    Arriving from an earlier phase (cursor on a passport/emotion step) seeds the
    first additional outfit; a resumed cursor already on an outfit is preserved.
    """
    state = session.character
    if state is not None and session.current_screen is ScreenId.OUTFITS:
        session.outfit_pending_delete = None
        session.outfit_pending_approve_confirm = False
        if state.outfits_enabled and current_outfit_index(state) is None:
            first = first_outfit_step(state)
            if first is not None:
                state.current_step = first
        session.notice = ""
        _persist(session)
    return session


def on_outfit_prompt_edit(session: WizardSession, prompt: str) -> WizardSession:
    """Sync the editable clothing-prompt field back into the cursor outfit."""
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        state.outfits[index].prompt = prompt.strip()
        _persist(session)
    return session


def on_outfit_detail_prompt_edit(session: WizardSession, prompt: str, *, j: int) -> WizardSession:
    """Persist an edited costume-detail prompt (cell ``j``, 0-based) into state.

    ``j`` is keyword-only so the Gradio wiring can bind it via ``partial`` while
    the live textbox value rides in as the positional ``prompt`` input.
    """
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        details = state.outfits[index].details
        if 0 <= j < len(details):
            details[j].prompt = prompt.strip()
            _persist(session)
    return session


def on_toggle_outfit_complex(session: WizardSession, complex_: bool) -> WizardSession:
    """Toggle the cursor outfit's "complex" flag (adds/hides profile + details)."""
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        session.outfit_pending_delete = None  # an unrelated action dismisses a pending delete
        set_outfit_complex(state, index, complex_)
        _persist(session)
    return session


def on_outfit_scene_generate(session: WizardSession, scene_id: SceneId) -> WizardSession:
    """Generate one full-length scene for the cursor outfit and bill the call."""
    found = _current_outfit(session)
    if found is None:
        return session
    state, index = found
    session.outfit_pending_delete = None
    meter = CostLedger()
    result = generate_outfit_scene(state, index, scene_id, meter=meter)
    session.notice = (
        "Сцена готова."
        if result.ok
        else (result.error or "Не удалось сгенерировать. Попробуй ещё раз — промт сохранён.")
    )
    _attribute_cost(session, meter)
    return session


def on_outfit_scene_approve_toggle(
    session: WizardSession, scene_id: SceneId, approved: bool
) -> WizardSession:
    """Set a scene's per-preview "approved" flag (optimization-only, never gates)."""
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        attr = {
            SceneId.FRONT_FULL: "front_full",
            SceneId.BACK_FULL: "back_full",
            SceneId.PROFILE_FULL: "profile_full",
        }[scene_id]
        setattr(state.outfits[index].refs, f"{attr}_approved", bool(approved))
        _persist(session)
    return session


def on_outfit_detail_generate(session: WizardSession, j: int) -> WizardSession:
    """Generate costume-detail cell ``j`` (0-based) for the cursor outfit.

    The detail's prompt is persisted by :func:`on_outfit_detail_prompt_edit` (the
    textbox ``.blur`` fires before this click), so the stored text is used here.
    """
    found = _current_outfit(session)
    if found is None:
        return session
    state, index = found
    n = j + 1
    details = state.outfits[index].details
    if not 1 <= n <= len(details):
        return session
    session.outfit_pending_delete = None
    meter = CostLedger()
    result = generate_outfit_detail(state, index, n, meter=meter)
    session.notice = (
        "Деталь готова." if result.ok else (result.error or "Не удалось сгенерировать деталь.")
    )
    _attribute_cost(session, meter)
    return session


def on_outfit_add_detail(session: WizardSession) -> WizardSession:
    """Append an empty costume-detail slot to the cursor outfit (capped)."""
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        session.outfit_pending_delete = None
        add_outfit_detail(state, index)
        _persist(session)
    return session


def on_outfit_delete_detail(session: WizardSession, j: int) -> WizardSession:
    """Delete detail ``j`` (0-based); a generated detail first asks to confirm (§5)."""
    found = _current_outfit(session)
    if found is None:
        return session
    state, index = found
    n = j + 1
    if detail_has_generation(state, index, n):
        session.outfit_pending_delete = (index, n)  # reveal the confirm button
        session.notice = "У детали есть генерация — подтверди удаление."
        return session
    delete_outfit_detail(state, index, n)
    session.outfit_pending_delete = None
    _persist(session)
    return session


def on_outfit_delete_detail_confirmed(session: WizardSession, j: int) -> WizardSession:
    """Confirm deletion of a generated costume detail."""
    found = _current_outfit(session)
    if found is not None:
        state, index = found
        delete_outfit_detail(state, index, j + 1)
    session.outfit_pending_delete = None
    _persist(session)
    return session


def on_approve_outfit(session: WizardSession) -> WizardSession:
    """Approve the cursor outfit (gated on required scenes) → next outfit or phase."""
    found = _current_outfit(session)
    if found is None:
        return session
    state, index = found
    outfit = state.outfits[index]
    session.outfit_pending_delete = None
    if not required_scenes_present(outfit):
        session.notice = "Сгенерируй обязательные сцены наряда (фас + спина" + (
            " + профиль)." if outfit.complex else ")."
        )
        return session
    # A detail with a prompt but no generation → ask once (§5). A second Approve
    # proceeds; details persist (nothing is deleted), so this is a soft confirm.
    has_pending_detail = any(d.prompt.strip() and not d.ref for d in outfit.details)
    if has_pending_detail and not session.outfit_pending_approve_confirm:
        session.outfit_pending_approve_confirm = True
        session.notice = (
            "Есть деталь с промтом без генерации. Сгенерируй её или нажми "
            "«Согласовать наряд» ещё раз, чтобы продолжить."
        )
        return session
    session.outfit_pending_approve_confirm = False
    approve_outfit(state, index)  # required scenes present → marks approved + active
    nxt = adjacent_outfit_step(state, index, forward=True)
    if nxt is not None:
        state.current_step = nxt  # next outfit, stay on the screen
        session.notice = "Наряд согласован — следующий наряд."
    else:
        session.current_screen = next_screen(session)  # phase done
        session.notice = ""
    _persist(session)
    return session


def on_outfits_back(session: WizardSession) -> WizardSession:
    """Step back: previous outfit, or out of the phase from the first outfit."""
    session.outfit_pending_delete = None
    session.outfit_pending_approve_confirm = False
    found = _current_outfit(session)
    if found is None:
        session.current_screen = previous_screen(session)
        _persist(session)
        return session
    state, index = found
    prev = adjacent_outfit_step(state, index, forward=False)
    if prev is not None:
        state.current_step = prev
    else:
        session.current_screen = previous_screen(session)
    _persist(session)
    return session


# --------------------------------------------------------------------------- #
# Props phase (optional) — one prop at a time, 1..3 product shots (window 6, §5)
# --------------------------------------------------------------------------- #
def _current_prop(session: WizardSession) -> tuple[CharacterState, int] | None:
    """The character + cursor prop index, or ``None`` (no character / no prop)."""
    state = session.character
    if state is None:
        return None
    index = current_prop_index(state)
    return (state, index) if index is not None else None


def on_enter_props(session: WizardSession) -> WizardSession:
    """Mark the props phase: cursor → the first prop, unless already on one."""
    state = session.character
    if state is not None and session.current_screen is ScreenId.PROPS:
        session.prop_pending_delete = None
        if state.props_enabled and current_prop_index(state) is None:
            first = first_prop_step(state)
            if first is not None:
                state.current_step = first
        session.notice = ""
        _persist(session)
    return session


def on_prop_shot_what_edit(session: WizardSession, what: str, *, j: int) -> WizardSession:
    """Persist the edited "what is it" field of shot ``j`` (0-based)."""
    found = _current_prop(session)
    if found is not None:
        state, index = found
        shots = state.props[index].shots
        if 0 <= j < len(shots):
            shots[j].what = what.strip()
            _persist(session)
    return session


def on_prop_shot_prompt_edit(session: WizardSession, prompt: str, *, j: int) -> WizardSession:
    """Persist the edited generation prompt of shot ``j`` (0-based)."""
    found = _current_prop(session)
    if found is not None:
        state, index = found
        shots = state.props[index].shots
        if 0 <= j < len(shots):
            shots[j].prompt = prompt.strip()
            _persist(session)
    return session


def on_prop_shot_generate(session: WizardSession, j: int) -> WizardSession:
    """Generate product-shot cell ``j`` (0-based) for the cursor prop (no character)."""
    found = _current_prop(session)
    if found is None:
        return session
    state, index = found
    n = j + 1
    if not 1 <= n <= len(state.props[index].shots):
        return session
    session.prop_pending_delete = None
    meter = CostLedger()
    result = generate_prop_shot(state, index, n, meter=meter)
    session.notice = (
        "Кадр готов." if result.ok else (result.error or "Не удалось сгенерировать кадр.")
    )
    _attribute_cost(session, meter)
    return session


def on_prop_add_shot(session: WizardSession) -> WizardSession:
    """Append an empty product-shot slot to the cursor prop (capped at 3)."""
    found = _current_prop(session)
    if found is not None:
        state, index = found
        session.prop_pending_delete = None
        add_prop_shot(state, index)
        _persist(session)
    return session


def on_prop_delete_shot(session: WizardSession, j: int) -> WizardSession:
    """Delete shot ``j`` (0-based); a generated shot first asks to confirm (§5)."""
    found = _current_prop(session)
    if found is None:
        return session
    state, index = found
    n = j + 1
    if shot_has_generation(state, index, n):
        session.prop_pending_delete = (index, n)
        session.notice = "У кадра есть генерация — подтверди удаление."
        return session
    delete_prop_shot(state, index, n)
    session.prop_pending_delete = None
    _persist(session)
    return session


def on_prop_delete_shot_confirmed(session: WizardSession, j: int) -> WizardSession:
    """Confirm deletion of a generated product shot."""
    found = _current_prop(session)
    if found is not None:
        state, index = found
        delete_prop_shot(state, index, j + 1)
    session.prop_pending_delete = None
    _persist(session)
    return session


def on_props_forward(session: WizardSession) -> WizardSession:
    """Advance to the next prop, or out of the (optional, ungated) props phase."""
    session.prop_pending_delete = None
    found = _current_prop(session)
    if found is None:
        session.current_screen = next_screen(session)
        _persist(session)
        return session
    state, index = found
    nxt = adjacent_prop_step(state, index, forward=True)
    if nxt is not None:
        state.current_step = nxt
        session.notice = "Следующий предмет."
    else:
        session.current_screen = next_screen(session)
        session.notice = ""
    _persist(session)
    return session


def on_props_back(session: WizardSession) -> WizardSession:
    """Step back: previous prop, or out of the phase from the first prop."""
    session.prop_pending_delete = None
    found = _current_prop(session)
    if found is None:
        session.current_screen = previous_screen(session)
        _persist(session)
        return session
    state, index = found
    prev = adjacent_prop_step(state, index, forward=False)
    if prev is not None:
        state.current_step = prev
    else:
        session.current_screen = previous_screen(session)
    _persist(session)
    return session


def _rows(rows: object) -> list[list[object]]:
    """Coerce a Gradio dataframe value (list of rows, or ``{"data": [...]}``)."""
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    if not isinstance(rows, list):
        return []
    return [list(r) for r in rows]
