"""HF Spaces entry point.

Hugging Face Spaces expects a top-level ``app.py`` that exposes a ``demo``
variable (a ``gr.Blocks`` or ``gr.Interface`` instance). The actual
implementation lives inside the package so the src-layout and linters apply.
"""

from create_char_passport.gradio_app import build_demo
from create_char_passport.observability import init_sentry

init_sentry()

demo = build_demo()

if __name__ == "__main__":
    demo.launch()
