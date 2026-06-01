"""Gradio application factory for HF Spaces.

The wizard's heavy lifting lives in :mod:`create_char_passport.screens`,
:mod:`create_char_passport.state` and friends. This module's only job is
to assemble the screens into a single ``gr.Blocks`` and own the
per-session ``WizardSession`` state object.
"""

from __future__ import annotations

import gradio as gr

from create_char_passport.screens import (
    SCREEN_ORDER,
    ScreenId,
    WizardSession,
    build_screens,
)


def build_demo() -> gr.Blocks:
    """Return the wizard's ``gr.Blocks`` demo.

    Screens are rendered once and stay mounted; only their ``visible``
    attribute is toggled, which keeps the gr.State + back/forward gates
    simple. Each session gets its own :class:`WizardSession` instance.
    """
    with gr.Blocks(title="Create Char Passport") as demo:
        gr.Markdown("# Create Char Passport")
        # Per-session wizard state; defaults to the Home screen.
        gr.State(WizardSession())
        handles = build_screens()
        if set(handles.keys()) != set(SCREEN_ORDER):
            missing = set(SCREEN_ORDER) - set(handles.keys())
            msg = f"screens missing from build_screens(): {sorted(s.value for s in missing)}"
            raise RuntimeError(msg)
        _ = ScreenId  # re-export for downstream tests / consumers
    return demo
