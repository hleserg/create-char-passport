"""Gradio render functions + the glue that turns a session into UI updates.

Rendering stays thin: each ``render_<screen>`` builds a ``gr.Group`` (hidden
unless it is the home screen) and stashes the interactive components it owns in
``ScreenHandle.components`` so :func:`create_char_passport.gradio_app.build_demo`
can wire events to the pure handlers. Step-generation screens (passport,
emotions, outfits, props, dataset) remain foundation stubs — they belong to
tasks 3–5 of the epic; this task fills in HOME, STYLE and CHAR_DATA.

The ``*_refresh`` / ``screen_visibility`` helpers are the only Gradio-aware
logic here. They are module-level (not lambdas) so they are unit-tested
directly and the ``build_demo`` wiring stays lambda-free and coverable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import gradio as gr

from create_char_passport.ai import AIEditSlot, AISlot, build_ai_check_slot, build_ai_edit_slot
from create_char_passport.gen import build_prompt_layers, build_step_overrides
from create_char_passport.screens.handlers import on_update_table
from create_char_passport.screens.router import (
    SCREEN_ORDER,
    ScreenId,
    WizardSession,
)
from create_char_passport.state import CHARACTER_TABLE_FIELDS, CHARACTER_TABLE_KEYS, CostLedger
from create_char_passport.storage import character_asset
from create_char_passport.wizard import (
    BASE_OUTFIT_PLACEHOLDER,
    base_outfit_display,
    emotion_rows,
    outfit_rows,
    preset_labels,
    prop_rows,
    table_from_state,
)
from create_char_passport.wizard.emotions import (
    BASE_EMOTION_DESCRIPTION,
    BASE_EMOTION_HINT,
)
from create_char_passport.wizard.outfits import (
    FULL_LENGTH_HINT,
    MAX_OUTFIT_DETAILS,
    current_outfit_index,
    required_scenes_present,
)
from create_char_passport.wizard.passport import (
    COMMON_CRITERIA,
    FACE_BODY_HINT,
    NOTICE,
    cascade_warning,
    current_passport_step,
    editable_layers,
    frame_criterion,
    frame_title,
)


@dataclass(slots=True)
class ScreenHandle:
    """Bundle a screen's root container with its reserved AI slots + components."""

    screen: ScreenId
    container: gr.Group
    prompt: gr.Textbox | None = None
    ai_check: AISlot | None = None
    ai_edit: AIEditSlot | None = None
    components: dict[str, Any] = field(default_factory=dict)


# Fixed order of CHAR_DATA components refreshed when the screen is (re)entered.
CHAR_DATA_REFRESH_KEYS: tuple[str, ...] = (
    "char_title",
    *(f"table_{key}" for key in CHARACTER_TABLE_KEYS),
    "base_outfit",
    "emotions_enabled",
    "emotion_table",
    "base_emotion_enabled",
    "base_emotion_value",
    "outfits_enabled",
    "outfit_table",
    "props_enabled",
    "prop_table",
)


def _heading(screen: ScreenId, body: str) -> None:
    gr.Markdown(f"## {screen.value}\n\n{body}")


def _nav_buttons(prefix: str) -> tuple[gr.Button, gr.Button]:
    with gr.Row():
        back = gr.Button("← Back", elem_id=f"{prefix}-back")
        fwd = gr.Button("Forward →", elem_id=f"{prefix}-forward")
    return back, fwd


# --------------------------------------------------------------------------- #
# HOME
# --------------------------------------------------------------------------- #
def render_home() -> ScreenHandle:
    """Start screen — extract from text + open a saved character."""
    components: dict[str, Any] = {}
    with gr.Group(visible=True) as group:
        _heading(ScreenId.HOME, "Paste a text and extract characters, or pick a saved one.")
        components["text"] = gr.Textbox(label="Story text", lines=8, interactive=True)
        components["extract_btn"] = gr.Button("Extract characters (LLM)", variant="primary")
        components["notice"] = gr.Markdown("")
        components["extracted"] = gr.Dropdown(
            label="Extracted characters", choices=[], interactive=True
        )
        components["open_extracted_btn"] = gr.Button("Open character data →")
        components["saved"] = gr.Dropdown(
            label="Saved characters (from bucket)", choices=[], interactive=True
        )
        components["open_saved_btn"] = gr.Button("Open saved")
    return ScreenHandle(screen=ScreenId.HOME, container=group, components=components)


# --------------------------------------------------------------------------- #
# STYLE
# --------------------------------------------------------------------------- #
def render_style() -> ScreenHandle:
    """Style step — upload ~5 photos, draft the STYLE prompt, approve to freeze."""
    components: dict[str, Any] = {}
    with gr.Group(visible=False) as group:
        _heading(
            ScreenId.STYLE,
            "Upload ~5 style reference photos so the LLM can draft the STYLE prompt.",
        )
        components["images"] = gr.File(
            label="Style reference photos", file_count="multiple", type="filepath"
        )
        components["draft_btn"] = gr.Button("Draft style prompt (LLM)", variant="primary")
        components["style_text"] = gr.Textbox(
            label="STYLE prompt (edit before approving)", lines=6, interactive=True
        )
        components["approve_btn"] = gr.Button("Approve style → character data", variant="primary")
    return ScreenHandle(screen=ScreenId.STYLE, container=group, components=components)


# --------------------------------------------------------------------------- #
# CHAR_DATA
# --------------------------------------------------------------------------- #
def render_char_data() -> ScreenHandle:
    """Character-data screen — trait table + the four optional blocks."""
    components: dict[str, Any] = {}
    with gr.Group(visible=False) as group:
        components["char_title"] = gr.Markdown("## char_data")

        gr.Markdown("**Character table** — extraction is a draft; edit freely.")
        for tfield in CHARACTER_TABLE_FIELDS:
            lines = 3 if tfield.key == "details" else 1
            components[f"table_{tfield.key}"] = gr.Textbox(
                label=tfield.label, lines=lines, interactive=True
            )

        components["base_outfit"] = gr.Textbox(
            label="Base outfit (read-only — set on the passport step)",
            value=BASE_OUTFIT_PLACEHOLDER,
            interactive=False,
        )

        with gr.Group():
            components["emotions_enabled"] = gr.Checkbox(label="Emotions", value=False)
            components["emotion_table"] = gr.Dataframe(
                headers=["Emotion", "Reference"],
                datatype=["str", "str"],
                interactive=False,
                row_count=2,
                column_count=2,
            )

        with gr.Group():
            components["base_emotion_enabled"] = gr.Checkbox(
                label="Character base emotion", value=False
            )
            with gr.Row():
                components["base_emotion_value"] = gr.Textbox(
                    label="Base emotion (short English expression)", interactive=True
                )
                components["base_emotion_preset"] = gr.Dropdown(
                    label="… presets", choices=preset_labels(), interactive=True
                )

        with gr.Group():
            components["outfits_enabled"] = gr.Checkbox(label="Additional outfits", value=False)
            components["outfit_table"] = gr.Dataframe(
                headers=["Outfit prompt", "Complex"],
                datatype=["str", "bool"],
                interactive=False,
                row_count=1,
                column_count=2,
            )

        with gr.Group():
            components["props_enabled"] = gr.Checkbox(label="Props / magic", value=False)
            components["prop_table"] = gr.Dataframe(
                headers=["Item / effect"],
                datatype=["str"],
                interactive=False,
                row_count=1,
                column_count=1,
            )

        components["next_btn"] = gr.Button("Next → passport", variant="primary")
    return ScreenHandle(screen=ScreenId.CHAR_DATA, container=group, components=components)


# --------------------------------------------------------------------------- #
# Step / stub screens (foundation — owned by tasks 3–5)
# --------------------------------------------------------------------------- #
def _render_simple(screen: ScreenId, body: str) -> ScreenHandle:
    with gr.Group(visible=False) as group:
        _heading(screen, body)
        _nav_buttons(screen.value)
    return ScreenHandle(screen=screen, container=group)


def _render_step(
    screen: ScreenId,
    *,
    body: str,
    representative_step_key: str,
    with_edit_slot: bool,
) -> ScreenHandle:
    with gr.Group(visible=False) as group:
        _heading(screen, body)
        prompt = gr.Textbox(
            label="Prompt (current step)",
            lines=4,
            interactive=True,
            elem_id=f"{screen.value}-prompt",
        )
        ai_check = build_ai_check_slot(representative_step_key, prompt)
        ai_edit: AIEditSlot | None = None
        if with_edit_slot:
            ai_edit = build_ai_edit_slot(representative_step_key, prompt)
        _nav_buttons(screen.value)
    return ScreenHandle(
        screen=screen,
        container=group,
        prompt=prompt,
        ai_check=ai_check,
        ai_edit=ai_edit,
    )


# Components refreshed when the passport frame (re)renders, in fixed order.
PASSPORT_REFRESH_KEYS: tuple[str, ...] = (
    "heading",
    "criterion",
    "cascade",
    "status",
    "preview",
    "style_box",
    "face_box",
    "body_box",
    "outfit_box",
    "expression_box",
    "composition_box",
    "gen_btn",
    "approve_btn",
    "forward_btn",
)


def render_passport() -> ScreenHandle:
    """Unified passport step form — one screen, five frames (window 3, §5).

    A single ``gr.Group``; :func:`passport_refresh` repaints it per frame. FACE
    is the representative prompt for the (reserved) AI slots; the layer fields'
    interactivity is toggled per frame by the refresh glue.
    """
    components: dict[str, Any] = {}
    with gr.Group(visible=False) as group:
        components["heading"] = gr.Markdown("### Паспорт")
        gr.Markdown(f"**{NOTICE}**")
        components["criterion"] = gr.Markdown("")
        components["cascade"] = gr.Markdown("", visible=False)
        components["preview"] = gr.Image(label="Превью кадра", interactive=False, type="filepath")
        components["status"] = gr.Markdown("")

        gr.Markdown(f"_{FACE_BODY_HINT}_")
        components["style_box"] = gr.Textbox(label="STYLE (заморожен)", interactive=False, lines=2)
        components["face_box"] = gr.Textbox(
            label="FACE — лицо / идентичность", lines=3, interactive=True, elem_id="passport-prompt"
        )
        components["body_box"] = gr.Textbox(
            label="BODY — телосложение / приметы", lines=3, interactive=True
        )
        components["outfit_box"] = gr.Textbox(
            label="OUTFIT — базовый наряд", lines=2, interactive=True
        )
        components["expression_box"] = gr.Textbox(label="EXPRESSION", interactive=False)
        components["composition_box"] = gr.Textbox(
            label="COMPOSITION (сцена кадра)", interactive=False, lines=4
        )

        prompt = components["face_box"]
        ai_check = build_ai_check_slot("passport_face", prompt)
        ai_edit = build_ai_edit_slot("passport_face", prompt)

        with gr.Row():
            components["gen_btn"] = gr.Button(
                "Сгенерировать", variant="primary", elem_id="passport-generate"
            )
            components["approve_btn"] = gr.Button(
                "Утвердить", variant="primary", elem_id="passport-approve"
            )
        with gr.Row():
            components["back_btn"] = gr.Button("← Назад", elem_id="passport-back")
            components["forward_btn"] = gr.Button("Вперёд →", elem_id="passport-forward")
    return ScreenHandle(
        screen=ScreenId.PASSPORT,
        container=group,
        prompt=prompt,
        ai_check=ai_check,
        ai_edit=ai_edit,
        components=components,
    )


# Components refreshed when the emotions screen (re)renders, in fixed order.
EMOTIONS_REFRESH_KEYS: tuple[str, ...] = (
    "emotion_row",
    "emo_cell_0",
    "emo_label_0",
    "emo_preview_0",
    "emo_cell_1",
    "emo_label_1",
    "emo_preview_1",
    "emo_cell_2",
    "emo_label_2",
    "emo_preview_2",
    "base_emotion_enabled",
    "base_emotion_value",
    "base_emotion_block",
    "base_emotion_preview",
    "status",
    "skip_btn",
)

# Max emotion cells the screen pre-builds. The default series has 2 (the
# non-neutral expressions); a legacy saved character may carry up to 3 (incl.
# its old "neutral"). Cells beyond the character's own ``items`` are hidden at
# refresh, so the layout adapts to either count without rebuilding.
_EMOTION_CELLS: int = 3


def render_emotions() -> ScreenHandle:
    """Emotions screen (window 4) — a row of 3 point-wise emotion portraits + base emotion."""
    components: dict[str, Any] = {}
    with gr.Group(visible=False) as group:
        _heading(ScreenId.EMOTIONS, "Сгенерируй портрет для каждой эмоции (по кнопке под кадром).")
        with gr.Row() as emotion_row:
            for i in range(_EMOTION_CELLS):
                with gr.Column() as emo_cell:
                    components[f"emo_label_{i}"] = gr.Markdown(f"**эмоция {i + 1}**")
                    components[f"emo_preview_{i}"] = gr.Image(
                        label="Превью", interactive=False, type="filepath"
                    )
                    components[f"emo_gen_{i}"] = gr.Button(
                        "Сгенерировать", elem_id=f"emotion-generate-{i}"
                    )
                components[f"emo_cell_{i}"] = emo_cell
        # The series row is hidden in a base-only state (Emotions block off) so its
        # generate buttons are unreachable and can't bill out-of-pipeline frames.
        components["emotion_row"] = emotion_row

        components["base_emotion_enabled"] = gr.Checkbox(
            label="Базовая эмоция персонажа", value=False
        )
        with gr.Group(visible=False) as base_block:
            gr.Markdown(f"_{BASE_EMOTION_DESCRIPTION}_")
            with gr.Row():
                components["base_emotion_value"] = gr.Textbox(
                    label="Базовая эмоция (короткое выражение, англ.)", interactive=True
                )
                components["base_emotion_preset"] = gr.Dropdown(
                    label="… пресеты", choices=preset_labels(), interactive=True
                )
            gr.Markdown(f"_{BASE_EMOTION_HINT}_")
            components["base_emotion_gen"] = gr.Button(
                "Сгенерировать базовую эмоцию", elem_id="base-emotion-generate"
            )
            components["base_emotion_preview"] = gr.Image(
                label="Превью базовой эмоции", interactive=False, type="filepath"
            )
            prompt = components["base_emotion_value"]
            ai_check = build_ai_check_slot("base_emotion", prompt)
        components["base_emotion_block"] = base_block

        components["status"] = gr.Markdown("")
        with gr.Row():
            components["back_btn"] = gr.Button("← Назад", elem_id="emotions-back")
            components["approve_btn"] = gr.Button(
                "Утвердить", variant="primary", elem_id="emotions-approve"
            )
            components["skip_btn"] = gr.Button(
                "Перейти как есть →", visible=False, elem_id="emotions-skip"
            )
    return ScreenHandle(
        screen=ScreenId.EMOTIONS,
        container=group,
        prompt=prompt,
        ai_check=ai_check,
        ai_edit=None,
        components=components,
    )


# The outfit screen shows ONE additional outfit at a time (repainted per cursor),
# with up to this many costume-detail cells when the outfit is complex (the cap
# is shared with the wizard so the add path never outruns the rendered cells).
_OUTFIT_DETAIL_CELLS: int = MAX_OUTFIT_DETAILS
# (OutfitRefs attribute, preview label) per full-length scene, in fixed order.
_OUTFIT_ANGLES: tuple[tuple[str, str], ...] = (
    ("front_full", "Фас, полный рост"),
    ("back_full", "Спина, полный рост"),
    ("profile_full", "Профиль, полный рост"),
)


def _outfits_refresh_keys() -> tuple[str, ...]:
    keys: list[str] = ["outfit_label", "outfit_prompt", "complex_toggle", "status"]
    for attr, _label in _OUTFIT_ANGLES:
        keys += [f"{attr}_block", f"{attr}_preview", f"{attr}_approved"]
    keys.append("detail_block")
    for j in range(_OUTFIT_DETAIL_CELLS):
        keys += [
            f"detail_cell_{j}",
            f"detail_prompt_{j}",
            f"detail_preview_{j}",
            f"detail_delete_confirm_{j}",
        ]
    keys += ["add_detail_btn", "approve_btn"]
    return tuple(keys)


# Components repainted when the outfit screen (re)renders, in fixed order.
OUTFITS_REFRESH_KEYS: tuple[str, ...] = _outfits_refresh_keys()


def render_outfits() -> ScreenHandle:
    """Outfit step (window 5, §5) — one additional outfit at a time.

    A single ``gr.Group`` repainted by :func:`outfits_refresh` per cursor
    (``current_step == outfit_<id>``): the clothing prompt, the "complex" toggle,
    front/back full-length scenes (+ profile when complex), and the costume-detail
    block (complex only). ``ai_check`` slots are reserved empty containers (K4,
    filled by task 6); the per-preview "Утверждено" checkbox is optimization-only.
    """
    components: dict[str, Any] = {}
    with gr.Group(visible=False) as group:
        gr.Markdown("### Наряд")
        components["outfit_label"] = gr.Markdown("")
        gr.Markdown(f"_{FULL_LENGTH_HINT}_")
        components["outfit_prompt"] = gr.Textbox(
            label="Промт одежды", lines=2, interactive=True, elem_id="outfit-prompt"
        )
        components["complex_toggle"] = gr.Checkbox(label="Сложный наряд", value=False)
        components["status"] = gr.Markdown("")

        prompt = components["outfit_prompt"]
        ai_check = build_ai_check_slot("outfit_step", prompt)

        with gr.Row():
            for attr, label in _OUTFIT_ANGLES:
                with gr.Group() as block:
                    components[f"{attr}_preview"] = gr.Image(
                        label=label, interactive=False, type="filepath"
                    )
                    components[f"{attr}_gen"] = gr.Button(
                        "Сгенерировать", elem_id=f"outfit-{attr.replace('_', '-')}-generate"
                    )
                    components[f"{attr}_approved"] = gr.Checkbox(label="Утверждено", value=False)
                components[f"{attr}_block"] = block

        with gr.Group(visible=False) as detail_block:
            gr.Markdown("**Детали костюма** (крупные планы — только стиль + этот наряд)")
            for j in range(_OUTFIT_DETAIL_CELLS):
                with gr.Group(visible=False) as cell:
                    components[f"detail_prompt_{j}"] = gr.Textbox(
                        label=f"Деталь {j + 1}", lines=1, interactive=True
                    )
                    components[f"detail_preview_{j}"] = gr.Image(
                        label="Превью детали", interactive=False, type="filepath"
                    )
                    components[f"detail_ai_check_{j}"] = build_ai_check_slot(
                        "outfit_detail_step", components[f"detail_prompt_{j}"]
                    )
                    with gr.Row():
                        components[f"detail_gen_{j}"] = gr.Button(
                            "Сгенерировать деталь", elem_id=f"outfit-detail-generate-{j}"
                        )
                        components[f"detail_delete_{j}"] = gr.Button(
                            "Удалить", elem_id=f"outfit-detail-delete-{j}"
                        )
                        components[f"detail_delete_confirm_{j}"] = gr.Button(
                            "Удалить с генерацией",
                            variant="stop",
                            visible=False,
                            elem_id=f"outfit-detail-delete-confirm-{j}",
                        )
                components[f"detail_cell_{j}"] = cell
            components["add_detail_btn"] = gr.Button("+ деталь", elem_id="outfit-add-detail")
        components["detail_block"] = detail_block

        with gr.Row():
            components["back_btn"] = gr.Button("← Назад", elem_id="outfits-back")
            components["approve_btn"] = gr.Button(
                "Согласовать наряд", variant="primary", elem_id="outfits-approve"
            )
    return ScreenHandle(
        screen=ScreenId.OUTFITS,
        container=group,
        prompt=prompt,
        ai_check=ai_check,
        ai_edit=None,
        components=components,
    )


def outfits_refresh(session: WizardSession) -> list[Any]:
    """Repaint the outfit screen for the cursor's outfit, in ``OUTFITS_REFRESH_KEYS`` order.

    No character, or a cursor that resolves to no outfit → all no-op updates
    (plus the status line). Per outfit: clothing prompt + complex toggle, each
    angle preview (profile hidden when simple), the costume-detail cells (shown
    only when complex), the delete-confirm affordance (driven by the session's
    pending-delete flag), and the Approve button gated on scene *presence*.
    """
    state = session.character
    values: dict[str, Any] = dict.fromkeys(OUTFITS_REFRESH_KEYS, gr.update())
    values["status"] = gr.update(value=session.notice or "")
    if state is None:
        return [values[k] for k in OUTFITS_REFRESH_KEYS]
    idx = current_outfit_index(state)
    if idx is None:
        return [values[k] for k in OUTFITS_REFRESH_KEYS]
    outfit = state.outfits[idx]

    complex_ = outfit.complex
    values["outfit_label"] = gr.update(
        value=f"**Наряд {idx + 1} из {len(state.outfits)}:** {outfit.prompt.strip() or '—'}"
    )
    values["outfit_prompt"] = gr.update(value=outfit.prompt)
    values["complex_toggle"] = gr.update(value=complex_)
    for attr, _label in _OUTFIT_ANGLES:
        ref = getattr(outfit.refs, attr)
        preview: str | None = None
        if ref:
            path = character_asset(state.character_id, ref)
            if path.is_file():
                preview = str(path)
        values[f"{attr}_block"] = gr.update(visible=complex_ if attr == "profile_full" else True)
        values[f"{attr}_preview"] = gr.update(value=preview)
        values[f"{attr}_approved"] = gr.update(value=getattr(outfit.refs, f"{attr}_approved"))

    values["detail_block"] = gr.update(visible=complex_)
    for j in range(_OUTFIT_DETAIL_CELLS):
        detail = outfit.details[j] if (complex_ and j < len(outfit.details)) else None
        values[f"detail_cell_{j}"] = gr.update(visible=detail is not None)
        values[f"detail_prompt_{j}"] = gr.update(value=detail.prompt if detail else "")
        dpreview: str | None = None
        if detail is not None and detail.ref:
            dpath = character_asset(state.character_id, detail.ref)
            if dpath.is_file():
                dpreview = str(dpath)
        values[f"detail_preview_{j}"] = gr.update(value=dpreview)
        pending = session.outfit_pending_delete == (idx, j + 1)
        values[f"detail_delete_confirm_{j}"] = gr.update(visible=pending)

    # The "+ деталь" button disables once the per-outfit detail cap is reached.
    values["add_detail_btn"] = gr.update(interactive=len(outfit.details) < _OUTFIT_DETAIL_CELLS)
    values["approve_btn"] = gr.update(interactive=required_scenes_present(outfit))
    return [values[k] for k in OUTFITS_REFRESH_KEYS]


def render_props() -> ScreenHandle:
    return _render_step(
        ScreenId.PROPS,
        body="Props / magic — product shots, no character in frame.",
        representative_step_key="prop_step",
        with_edit_slot=False,
    )


def render_dataset() -> ScreenHandle:
    return _render_step(
        ScreenId.DATASET,
        body="Dataset phase — iterate composition array, approved/ vs rejected/.",
        representative_step_key="dataset_step",
        with_edit_slot=True,
    )


def render_finish() -> ScreenHandle:
    return _render_simple(
        ScreenId.FINISH,
        "All done — archive of approved/ + rejected/ ready for download.",
    )


_RENDERERS: dict[ScreenId, Any] = {
    ScreenId.HOME: render_home,
    ScreenId.STYLE: render_style,
    ScreenId.CHAR_DATA: render_char_data,
    ScreenId.PASSPORT: render_passport,
    ScreenId.EMOTIONS: render_emotions,
    ScreenId.OUTFITS: render_outfits,
    ScreenId.PROPS: render_props,
    ScreenId.DATASET: render_dataset,
    ScreenId.FINISH: render_finish,
}


def build_screens() -> dict[ScreenId, ScreenHandle]:
    """Render every screen once; visibility is toggled later by the router."""
    return {screen: _RENDERERS[screen]() for screen in SCREEN_ORDER}


# --------------------------------------------------------------------------- #
# Gradio glue — session -> component updates (module-level, unit-tested)
# --------------------------------------------------------------------------- #
def screen_visibility(session: WizardSession) -> list[Any]:
    """Visibility update for every screen container, in ``SCREEN_ORDER``."""
    return [gr.update(visible=screen == session.current_screen) for screen in SCREEN_ORDER]


def home_refresh(session: WizardSession) -> list[Any]:
    """Updates for [notice, extracted dropdown, saved dropdown] on the home screen."""
    extracted = [c.name for c in session.extracted_characters]
    saved = saved_choices()
    return [
        gr.update(value=session.notice),
        gr.update(choices=extracted, value=extracted[0] if extracted else None),
        gr.update(choices=saved, value=saved[0][1] if saved else None),
    ]


def saved_choices() -> list[tuple[str, str]]:
    """``(label, character_id)`` pairs for the saved-characters dropdown."""
    from create_char_passport.wizard import saved_characters

    return [(f"{row.name} — {row.status}", row.character_id) for row in saved_characters()]


def char_data_refresh(session: WizardSession) -> list[Any]:
    """Updates for every CHAR_DATA component, in :data:`CHAR_DATA_REFRESH_KEYS` order.

    No character -> no-op updates (the screen is not visible anyway).
    """
    state = session.character
    if state is None:
        return [gr.update() for _ in CHAR_DATA_REFRESH_KEYS]
    table = table_from_state(state)
    emotions_on = state.emotions.enabled
    values: dict[str, Any] = {
        "char_title": gr.update(value=f"## Character: {state.name or state.character_id}"),
        "base_outfit": gr.update(value=base_outfit_display(state)),
        "emotions_enabled": gr.update(value=emotions_on),
        "emotion_table": gr.update(value=emotion_rows(state), interactive=emotions_on),
        "base_emotion_enabled": gr.update(value=state.emotions.base_emotion.enabled),
        "base_emotion_value": gr.update(
            value=state.emotions.base_emotion.value,
            interactive=state.emotions.base_emotion.enabled,
        ),
        "outfits_enabled": gr.update(value=state.outfits_enabled),
        "outfit_table": gr.update(value=outfit_rows(state), interactive=state.outfits_enabled),
        "props_enabled": gr.update(value=state.props_enabled),
        "prop_table": gr.update(value=prop_rows(state), interactive=state.props_enabled),
    }
    for key in CHARACTER_TABLE_KEYS:
        values[f"table_{key}"] = gr.update(value=table[key])
    return [values[key] for key in CHAR_DATA_REFRESH_KEYS]


def update_table_fields(session: WizardSession, *field_values: str) -> WizardSession:
    """Collect the trait-table textbox values into a dict and persist them."""
    table = dict(zip(CHARACTER_TABLE_KEYS, field_values, strict=False))
    return on_update_table(session, table)


def passport_refresh(session: WizardSession) -> list[Any]:
    """Updates for every passport component, in :data:`PASSPORT_REFRESH_KEYS` order.

    Repaints the single passport form for whichever frame the cursor is on:
    heading + criteria, the cascade banner (visible only when the frame is
    stale), the preview image, the six layer fields (with per-frame
    interactivity and forced EXPRESSION/COMPOSITION), and the button states
    (generate vs regenerate label; approve/forward enablement). No character ->
    all no-op updates (the screen is not visible anyway).
    """
    state = session.character
    if state is None:
        return [gr.update() for _ in PASSPORT_REFRESH_KEYS]
    step_key = current_passport_step(state)
    layers = build_prompt_layers(state, step_key, overrides=build_step_overrides(state, step_key))
    editable = editable_layers(step_key)
    record = state.steps.get(step_key)
    has_generation = record is not None and bool(record.last_path)
    is_approved = record is not None and bool(record.approved_path)
    warning = cascade_warning(state, step_key)

    preview: str | None = None
    if record is not None and record.last_path:
        path = character_asset(state.character_id, record.last_path)
        if path.is_file():
            preview = str(path)

    values: dict[str, Any] = {
        "heading": gr.update(value=f"### {frame_title(step_key)}"),
        "criterion": gr.update(
            value=f"**Критерий кадра:** {frame_criterion(step_key)}\n\n_{COMMON_CRITERIA}_"
        ),
        "cascade": gr.update(value=warning or "", visible=warning is not None),
        "status": gr.update(value=session.notice or ""),
        "preview": gr.update(value=preview),
        "style_box": gr.update(value=layers["style"]),
        "face_box": gr.update(value=layers["face"], interactive="face" in editable),
        "body_box": gr.update(value=layers["body"], interactive="body" in editable),
        "outfit_box": gr.update(
            value=layers["outfit"],
            interactive=("outfit" in editable) and not state.base_outfit.frozen,
        ),
        "expression_box": gr.update(value=layers["expression"]),
        "composition_box": gr.update(value=layers["composition"]),
        "gen_btn": gr.update(value="Перегенерить" if has_generation else "Сгенерировать"),
        "approve_btn": gr.update(interactive=has_generation),
        "forward_btn": gr.update(interactive=is_approved),
    }
    return [values[key] for key in PASSPORT_REFRESH_KEYS]


def emotions_refresh(session: WizardSession) -> list[Any]:
    """Updates for every emotions component, in :data:`EMOTIONS_REFRESH_KEYS` order.

    Repaints the 3 emotion cells (label + preview from ``items[].ref``), the base
    emotion block (shown only when enabled; value synced from the character) and
    the "skip with incomplete set" button (shown after Approve finds gaps). No
    character -> all no-op updates.
    """
    state = session.character
    if state is None:
        return [gr.update() for _ in EMOTIONS_REFRESH_KEYS]
    items = state.emotions.items
    base = state.emotions.base_emotion
    series_on = state.emotions.enabled
    values: dict[str, Any] = {"emotion_row": gr.update(visible=series_on)}
    for i in range(_EMOTION_CELLS):
        item = items[i] if (series_on and i < len(items)) else None
        preview: str | None = None
        if item is not None and item.ref:
            path = character_asset(state.character_id, item.ref)
            if path.is_file():
                preview = str(path)
        # Hide cells with no backing emotion (default series is shorter than the
        # pre-built cell count) so no empty cell with a dead generate button shows.
        values[f"emo_cell_{i}"] = gr.update(visible=item is not None)
        values[f"emo_label_{i}"] = gr.update(value=f"**{item.value}**" if item else "")
        values[f"emo_preview_{i}"] = gr.update(value=preview)

    base_preview: str | None = None
    if base.ref:
        path = character_asset(state.character_id, base.ref)
        if path.is_file():
            base_preview = str(path)
    values["base_emotion_enabled"] = gr.update(value=base.enabled)
    values["base_emotion_value"] = gr.update(value=base.value, interactive=base.enabled)
    values["base_emotion_block"] = gr.update(visible=base.enabled)
    values["base_emotion_preview"] = gr.update(value=base_preview)
    values["status"] = gr.update(value=session.notice or "")
    values["skip_btn"] = gr.update(visible=session.emotions_offer_skip)
    return [values[key] for key in EMOTIONS_REFRESH_KEYS]


def interactive_update(enabled: bool) -> Any:
    """A single ``gr.update(interactive=...)`` — greys a block out when off."""
    return gr.update(interactive=bool(enabled))


def _fmt_cost(ledger: CostLedger) -> str:
    """Format a ledger total, marking it ``≈`` only when it really is an estimate."""
    prefix = "≈" if ledger.has_estimate else ""
    return f"{prefix}${ledger.total_usd:.4f}"


def cost_banner_text(session: WizardSession) -> str:
    """Markdown for the global running-cost banner shown on every screen.

    Shows the active character's spend plus the session total (which also
    covers pre-character calls like extraction). A figure is marked ``≈`` only
    when an approximate / unknown list price actually fed into it (e.g. a
    preview image model) — see :mod:`create_char_passport.gen.pricing`.
    """
    session_total = _fmt_cost(session.cost)
    char = session.character
    if char is None:
        return f"💸 Сессия: {session_total}"
    name = char.name or char.character_id
    return f"💸 Персонаж «{name}»: {_fmt_cost(char.cost)} · Сессия: {session_total}"
