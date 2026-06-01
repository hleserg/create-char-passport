"""Gradio render functions — kept thin so the router carries the logic.

Each ``render_<screen>`` builds a ``gr.Group`` whose ``visible`` flag is
flipped by the router. Step-generation screens reserve the K4 AI slots
next to their prompt fields; passport + dataset additionally reserve the
``ai_edit_slot``. The actual UX (forms, previews, buttons) is *not* the
job of the foundation task — these are stubs that prove the skeleton
wires up.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import gradio as gr

from create_char_passport.ai import AIEditSlot, AISlot, build_ai_check_slot, build_ai_edit_slot
from create_char_passport.screens.router import SCREEN_ORDER, ScreenId


@dataclass(slots=True)
class ScreenHandle:
    """Bundle a screen's root container with its reserved AI slots."""

    screen: ScreenId
    container: gr.Group
    prompt: gr.Textbox | None = None
    ai_check: AISlot | None = None
    ai_edit: AIEditSlot | None = None


def _heading(screen: ScreenId, body: str) -> None:
    gr.Markdown(f"## {screen.value}\n\n{body}")


def _nav_buttons(prefix: str) -> tuple[gr.Button, gr.Button]:
    with gr.Row():
        back = gr.Button("← Back", elem_id=f"{prefix}-back")
        fwd = gr.Button("Forward →", elem_id=f"{prefix}-forward")
    return back, fwd


def render_home() -> ScreenHandle:
    """Start screen — text input + list of saved characters (stubbed)."""
    with gr.Group(visible=True) as group:
        _heading(
            ScreenId.HOME,
            "Paste a text and extract characters, or pick a saved one.",
        )
        gr.Textbox(label="Story text", lines=8, interactive=True)
        gr.Markdown("_Saved-characters list — wired in task 2._")
        _, fwd = _nav_buttons("home")
        _ = fwd  # foundation: button exists so layout doesn't shift
    return ScreenHandle(screen=ScreenId.HOME, container=group)


def _render_simple(screen: ScreenId, body: str) -> ScreenHandle:
    """Render a stub screen with heading + Back/Forward buttons only."""
    with gr.Group(visible=False) as group:
        _heading(screen, body)
        _nav_buttons(screen.value)
    return ScreenHandle(screen=screen, container=group)


def render_style() -> ScreenHandle:
    return _render_simple(
        ScreenId.STYLE,
        "Upload ~5 style reference photos so the LLM can draft the STYLE prompt.",
    )


def render_char_data() -> ScreenHandle:
    return _render_simple(
        ScreenId.CHAR_DATA,
        "Character data form — table, emotions, base outfit, additional outfits, props.",
    )


def _render_step(
    screen: ScreenId,
    *,
    body: str,
    representative_step_key: str,
    with_edit_slot: bool,
) -> ScreenHandle:
    """Render a step-generation stub with an editable prompt + AI slots."""
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
    """Render every screen once; visibility is toggled later by the router.

    The dict's insertion order matches :data:`SCREEN_ORDER` so callers can
    iterate in canonical wizard order.
    """
    return {screen: _RENDERERS[screen]() for screen in SCREEN_ORDER}
