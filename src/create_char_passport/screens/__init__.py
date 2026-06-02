"""Wizard router + per-screen stubs.

The wizard is a sequence of screens whose visibility is driven by a single
``gr.State`` (``WizardSession``) and an ordered list of ``ScreenId`` values.
Logic lives in :mod:`create_char_passport.screens.router` so it can be
unit-tested without Gradio in the loop; rendering lives in
:mod:`create_char_passport.screens.views`.
"""

from create_char_passport.screens.router import (
    SCREEN_ORDER,
    ScreenId,
    WizardSession,
    can_advance,
    next_screen,
    pending_regen_step,
    previous_screen,
    resume_screen,
    screen_for_step,
)
from create_char_passport.screens.views import (
    build_screens,
    render_home,
)

__all__ = [
    "SCREEN_ORDER",
    "ScreenId",
    "WizardSession",
    "build_screens",
    "can_advance",
    "next_screen",
    "pending_regen_step",
    "previous_screen",
    "render_home",
    "resume_screen",
    "screen_for_step",
]
