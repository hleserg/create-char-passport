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
from create_char_passport.gen.scenes import (
    SceneId,
    aspect_for_scene,
    aspect_for_step,
    build_step_overrides,
    clear_scene_override,
    default_composition,
    effective_composition,
    scene_for_step,
    set_scene_override,
)

__all__ = [
    "LAYER_ORDER",
    "GenerationResult",
    "Ref",
    "SceneId",
    "aspect_for_scene",
    "aspect_for_step",
    "build_prompt_layers",
    "build_step_overrides",
    "call_llm",
    "clear_scene_override",
    "default_composition",
    "effective_composition",
    "generate_image",
    "render_prompt_text",
    "scene_for_step",
    "set_scene_override",
]
