"""Tests for create_char_passport.gradio_app."""

from __future__ import annotations

import gradio as gr

from create_char_passport.gradio_app import build_demo


def test_build_demo_returns_blocks() -> None:
    demo = build_demo()
    assert isinstance(demo, gr.Blocks)
