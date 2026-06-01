"""Pure business logic for the wizard's input screens (HLE-727).

Everything here is Gradio-free so it can be unit-tested directly:

* :mod:`extraction` — extract characters (with traits) from the source text.
* :mod:`style` — draft + freeze the project STYLE prompt from reference photos.
* :mod:`presets` — the 12 base-emotion presets.
* :mod:`forms` — character-data form <-> state mapping, optional-block toggles,
  outfit/prop row tables, and the saved-character list / resume logic.

LLM calls ride the K2 engine (``create_char_passport.gen.call_llm``); the
Gradio screens in :mod:`create_char_passport.screens` wire thin event handlers
on top of these functions.
"""

from create_char_passport.wizard.extraction import (
    EXTRACTION_PROMPT,
    ExtractedCharacter,
    build_extraction_prompt,
    extract_characters,
    parse_extraction_response,
)
from create_char_passport.wizard.forms import (
    BASE_OUTFIT_PLACEHOLDER,
    SavedCharacter,
    apply_table,
    base_outfit_display,
    character_from_extracted,
    emotion_rows,
    outfit_rows,
    prop_rows,
    saved_characters,
    set_base_emotion,
    set_emotions_enabled,
    set_outfits_enabled,
    set_props_enabled,
    sync_outfits,
    sync_props,
    table_from_state,
)
from create_char_passport.wizard.presets import (
    BASE_EMOTION_PRESETS,
    EmotionPreset,
    preset_labels,
    value_for_label,
)
from create_char_passport.wizard.style import (
    STYLE_PROMPT,
    apply_style,
    draft_style_prompt,
)

__all__ = [
    "BASE_EMOTION_PRESETS",
    "BASE_OUTFIT_PLACEHOLDER",
    "EXTRACTION_PROMPT",
    "STYLE_PROMPT",
    "EmotionPreset",
    "ExtractedCharacter",
    "SavedCharacter",
    "apply_style",
    "apply_table",
    "base_outfit_display",
    "build_extraction_prompt",
    "character_from_extracted",
    "draft_style_prompt",
    "emotion_rows",
    "extract_characters",
    "outfit_rows",
    "parse_extraction_response",
    "preset_labels",
    "prop_rows",
    "saved_characters",
    "set_base_emotion",
    "set_emotions_enabled",
    "set_outfits_enabled",
    "set_props_enabled",
    "sync_outfits",
    "sync_props",
    "table_from_state",
    "value_for_label",
]
