"""Generation layer — single point of contact with the Gemini API.

* :mod:`create_char_passport.gen.engine` — contract K2 entrypoints
  (``generate_image`` + ``call_llm``).
* :mod:`create_char_passport.gen.prompt` — contract K3 prompt builder.
"""

from create_char_passport.gen.engine import (
    LAYER_ORDER,
    GenerationResult,
    Ref,
    call_llm,
    generate_image,
)
from create_char_passport.gen.prompt import build_prompt_layers, render_prompt_text

__all__ = [
    "LAYER_ORDER",
    "GenerationResult",
    "Ref",
    "build_prompt_layers",
    "call_llm",
    "generate_image",
    "render_prompt_text",
]
