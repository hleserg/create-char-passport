"""HF Spaces entry point.

Hugging Face Spaces expects a top-level ``app.py`` that exposes a ``demo``
variable (a ``gr.Blocks`` or ``gr.Interface`` instance). The actual
implementation lives inside the package so the src-layout and linters apply.
"""

import os

# Gradio 6 defaults to SSR — a Node proxy in front of the Python server. On HF
# Spaces that extra process is flaky: its event-loop teardown logs "Invalid file
# descriptor: -1" and can wedge the page. Serve the app directly instead. Set
# before importing the app so it applies whether Spaces runs this as __main__ or
# imports ``demo`` and launches it itself.
os.environ.setdefault("GRADIO_SSR_MODE", "false")

from create_char_passport.gradio_app import build_demo
from create_char_passport.observability import init_sentry

init_sentry()

demo = build_demo()

if __name__ == "__main__":
    demo.queue().launch(ssr_mode=False)
