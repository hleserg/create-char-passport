"""Gradio application factory for HF Spaces.

Import and call ``build_demo()`` to get a ``gr.Blocks`` instance.
The ``app.py`` at the repository root does exactly this so that HF Spaces
can find the demo via its expected entry-point file.
"""

from __future__ import annotations

import gradio as gr


def build_demo() -> gr.Blocks:
    """Return the Gradio Blocks demo (stub — foundation task HLE-726 fills this in)."""
    with gr.Blocks(title="Create Char Passport") as demo:
        gr.Markdown("# Create Char Passport\n_Stub — work in progress._")
    return demo
