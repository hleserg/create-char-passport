"""Tests for create_char_passport.gradio_app."""

from __future__ import annotations

import gradio as gr

from create_char_passport.gradio_app import build_demo


def test_build_demo_returns_blocks() -> None:
    demo = build_demo()
    assert isinstance(demo, gr.Blocks)


def test_build_demo_wires_a_load_handler() -> None:
    """The saved-characters list is refreshed on app open (``demo.load``).

    Guards the wiring the unit tests for ``home_refresh`` cannot: without a
    ``.load`` trigger a returning user sees an empty saved list until they pay
    for an extraction call.
    """
    demo = build_demo()
    triggers = {event for fn in demo.fns.values() for (_block, event) in getattr(fn, "targets", [])}
    assert "load" in triggers
