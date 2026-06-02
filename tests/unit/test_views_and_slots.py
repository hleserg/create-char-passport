"""Tests for the screen renderers and the K4 slot helpers."""

from __future__ import annotations

import gradio as gr

from create_char_passport.ai import AIEditSlot, AISlot, AISlotKind
from create_char_passport.screens import ScreenId, build_screens
from create_char_passport.screens.views import (
    render_home,
    render_passport,
)


def test_build_screens_returns_one_handle_per_screen() -> None:
    with gr.Blocks():
        handles = build_screens()
    for screen in ScreenId:
        assert screen in handles
        assert handles[screen].screen is screen


def test_passport_screen_has_both_ai_slots() -> None:
    with gr.Blocks():
        handle = render_passport()
    assert isinstance(handle.ai_check, AISlot)
    assert handle.ai_check.kind is AISlotKind.CHECK
    assert isinstance(handle.ai_edit, AIEditSlot)
    assert handle.ai_edit.kind is AISlotKind.EDIT
    assert handle.ai_check.context.step_key == "passport_step"  # cursor-resolved (HLE-731)
    assert handle.prompt is not None


def test_home_screen_has_no_ai_slots() -> None:
    with gr.Blocks():
        handle = render_home()
    assert handle.ai_check is None
    assert handle.ai_edit is None
    assert handle.prompt is None


def test_emotion_and_outfit_screens_have_check_slot_only() -> None:
    with gr.Blocks():
        handles = build_screens()
    assert handles[ScreenId.EMOTIONS].ai_check is not None
    assert handles[ScreenId.EMOTIONS].ai_edit is None
    assert handles[ScreenId.OUTFITS].ai_check is not None
    assert handles[ScreenId.OUTFITS].ai_edit is None


def test_dataset_screen_has_edit_slot() -> None:
    with gr.Blocks():
        handles = build_screens()
    assert handles[ScreenId.DATASET].ai_edit is not None
