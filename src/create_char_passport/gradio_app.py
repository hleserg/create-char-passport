"""Gradio application factory for HF Spaces.

The wizard's logic lives in :mod:`create_char_passport.screens.handlers` (pure
session mutators) and :mod:`create_char_passport.screens.views` (rendering +
session->update glue). This module only assembles the screens into one
``gr.Blocks``, owns the per-session ``WizardSession`` state, and wires events
to those functions — no behaviour of its own, so the wiring stays lambda-free
and every referenced callable is unit-tested elsewhere.
"""

from __future__ import annotations

import gradio as gr

from create_char_passport.screens import handlers
from create_char_passport.screens.router import SCREEN_ORDER, ScreenId, WizardSession
from create_char_passport.screens.views import (
    CHAR_DATA_REFRESH_KEYS,
    ScreenHandle,
    build_screens,
    char_data_refresh,
    home_refresh,
    interactive_update,
    screen_visibility,
    update_table_fields,
)
from create_char_passport.state import CHARACTER_TABLE_KEYS
from create_char_passport.wizard import value_for_label


def _wire_home(home: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Extract-from-text and open-saved / open-extracted transitions."""
    c = home.components
    home_outputs = [c["notice"], c["extracted"], c["saved"]]
    c["extract_btn"].click(handlers.on_extract, [session, c["text"]], [session]).then(
        home_refresh, [session], home_outputs
    )
    c["open_extracted_btn"].click(
        handlers.on_pick_extracted, [session, c["extracted"]], [session]
    ).then(char_data_refresh, [session], ctx.char_data_outputs).then(
        screen_visibility, [session], ctx.containers
    )
    c["open_saved_btn"].click(handlers.on_open_saved, [session, c["saved"]], [session]).then(
        char_data_refresh, [session], ctx.char_data_outputs
    ).then(screen_visibility, [session], ctx.containers)


def _wire_style(style: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Draft the style prompt and approve it (freezes STYLE, jumps to char-data)."""
    c = style.components
    c["draft_btn"].click(handlers.on_draft_style, [c["images"]], [c["style_text"]])
    c["approve_btn"].click(handlers.on_approve_style, [session, c["style_text"]], [session]).then(
        char_data_refresh, [session], ctx.char_data_outputs
    ).then(screen_visibility, [session], ctx.containers)


def _wire_char_data(char_data: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Trait-table edits + the four optional blocks + Next -> passport."""
    c = char_data.components
    table_fields = [c[f"table_{key}"] for key in CHARACTER_TABLE_KEYS]
    for field_box in table_fields:
        field_box.blur(update_table_fields, [session, *table_fields], [session])

    c["emotions_enabled"].change(
        handlers.on_toggle_emotions, [session, c["emotions_enabled"]], [session]
    ).then(interactive_update, [c["emotions_enabled"]], [c["emotion_table"]])

    base_emo_inputs = [session, c["base_emotion_enabled"], c["base_emotion_value"]]
    c["base_emotion_enabled"].change(
        handlers.on_update_base_emotion, base_emo_inputs, [session]
    ).then(interactive_update, [c["base_emotion_enabled"]], [c["base_emotion_value"]])
    c["base_emotion_value"].blur(handlers.on_update_base_emotion, base_emo_inputs, [session])
    c["base_emotion_preset"].change(
        value_for_label, [c["base_emotion_preset"]], [c["base_emotion_value"]]
    ).then(handlers.on_update_base_emotion, base_emo_inputs, [session])

    c["outfits_enabled"].change(
        handlers.on_toggle_outfits, [session, c["outfits_enabled"]], [session]
    ).then(interactive_update, [c["outfits_enabled"]], [c["outfit_table"]])
    c["outfit_table"].change(handlers.on_update_outfits, [session, c["outfit_table"]], [session])

    c["props_enabled"].change(
        handlers.on_toggle_props, [session, c["props_enabled"]], [session]
    ).then(interactive_update, [c["props_enabled"]], [c["prop_table"]])
    c["prop_table"].change(handlers.on_update_props, [session, c["prop_table"]], [session])

    c["next_btn"].click(handlers.on_next, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    )


class _Ctx:
    """Shared component references the per-screen wiring helpers need."""

    def __init__(self, handles: dict[ScreenId, ScreenHandle]) -> None:
        self.containers = [handles[screen].container for screen in SCREEN_ORDER]
        cd = handles[ScreenId.CHAR_DATA].components
        self.char_data_outputs = [cd[key] for key in CHAR_DATA_REFRESH_KEYS]


def build_demo() -> gr.Blocks:
    """Return the wizard's ``gr.Blocks`` demo.

    Screens are rendered once and stay mounted; only their ``visible``
    attribute is toggled, which keeps the ``gr.State`` + back/forward gates
    simple. Each session gets its own :class:`WizardSession` instance.
    """
    with gr.Blocks(title="Create Char Passport") as demo:
        gr.Markdown("# Create Char Passport")
        session = gr.State(WizardSession())
        handles = build_screens()
        if set(handles.keys()) != set(SCREEN_ORDER):
            missing = set(SCREEN_ORDER) - set(handles.keys())
            msg = f"screens missing from build_screens(): {sorted(s.value for s in missing)}"
            raise RuntimeError(msg)

        ctx = _Ctx(handles)
        home = handles[ScreenId.HOME]
        _wire_home(home, session, ctx)
        _wire_style(handles[ScreenId.STYLE], session, ctx)
        _wire_char_data(handles[ScreenId.CHAR_DATA], session, ctx)

        # Populate the saved-characters list from the bucket on app open, so a
        # returning user sees their characters without a paid extraction call.
        demo.load(
            home_refresh,
            [session],
            [home.components["notice"], home.components["extracted"], home.components["saved"]],
        )
    return demo
