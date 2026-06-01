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
from create_char_passport.screens.handlers import on_update_table
from create_char_passport.screens.router import (
    SCREEN_ORDER,
    ScreenId,
    WizardSession,
)
from create_char_passport.state import CHARACTER_TABLE_FIELDS, CHARACTER_TABLE_KEYS
from create_char_passport.wizard import (
    BASE_OUTFIT_PLACEHOLDER,
    base_outfit_display,
    emotion_rows,
    outfit_rows,
    preset_labels,
    prop_rows,
    table_from_state,
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
                row_count=3,
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


def render_passport() -> ScreenHandle:
    return _render_step(
        ScreenId.PASSPORT,
        body="Passport phase — 5 canonical frames. AI-check + AI-edit reserved.",
        representative_step_key="passport_face",
        with_edit_slot=True,
    )


def render_emotions() -> ScreenHandle:
    return _render_step(
        ScreenId.EMOTIONS,
        body="Emotions phase — 3 base emotions + optional base-emotion portrait.",
        representative_step_key="base_emotion",
        with_edit_slot=False,
    )


def render_outfits() -> ScreenHandle:
    return _render_step(
        ScreenId.OUTFITS,
        body="Additional outfits — one generation step per outfit row.",
        representative_step_key="outfit_step",
        with_edit_slot=False,
    )


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


def interactive_update(enabled: bool) -> Any:
    """A single ``gr.update(interactive=...)`` — greys a block out when off."""
    return gr.update(interactive=bool(enabled))


def _fmt_usd(amount: float) -> str:
    return f"${amount:.4f}"


def cost_banner_text(session: WizardSession) -> str:
    """Markdown for the global running-cost banner shown on every screen.

    Shows the active character's spend plus the session total (which also
    covers pre-character calls like extraction). The figure is an estimate —
    flagged with ``≈`` — because some image models are list-priced
    approximately (see :mod:`create_char_passport.gen.pricing`).
    """
    session_total = _fmt_usd(session.cost.total_usd)
    char = session.character
    if char is None:
        return f"💸 Сессия: ≈{session_total}"
    name = char.name or char.character_id
    return f"💸 Персонаж «{name}»: ≈{_fmt_usd(char.cost.total_usd)} · Сессия: ≈{session_total}"
