"""RU -> EN layer-prompt translation via one LLM call («⇄ по-русски», logic #2).

The user describes, in Russian, what they want in a given prompt layer; Gemini
turns it into an optimized English prompt for THAT layer. If the description also
mentions content that belongs to OTHER layers (e.g. clothing typed into the FACE
field), those are returned as per-layer suggestions so the UI can offer to fill
them too.

Rides the K2 engine (``call_llm``); parsing is tolerant (a broken reply degrades
to just the raw text, never raises).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from create_char_passport.gen import call_llm
from create_char_passport.state import CostLedger, coerce_value

# Canonical layer keys the model may return suggestions for (NOT the requested one).
_LAYER_KEYS: tuple[str, ...] = ("face", "body", "outfit", "expression", "composition", "style")

TRANSLATE_PROMPT: str = """\
You convert a Russian description into an optimized ENGLISH prompt for ONE layer
of a character-reference generation pipeline. The layers and their concerns:
- face: facial anatomy (shape, nose, lips, eyes, hair, skin, facial marks)
- body: build / proportions, body marks under clothing (NO clothing)
- outfit: clothing only (garments, cut, material, colour)
- expression: a short emotion/mood (e.g. "grim, brooding")
- composition: pose / camera / framing / background
- style: the drawing manner / medium / palette (NOT any character)

The user is writing the "{layer}" layer. Return STRICTLY a JSON object, no fences:
{
  "text": "the optimized ENGLISH prompt for the '{layer}' layer ONLY",
  "suggestions": { "<other_layer_key>": "english prompt for that layer", ... }
}
Rules:
- "text" must contain ONLY what belongs to the '{layer}' layer.
- If the Russian also describes OTHER layers, put each in "suggestions" keyed by
  the layer key (face/body/outfit/expression/composition/style); omit the
  requested layer from suggestions; empty object if nothing spilled over.
- English only, compact, comma-separated where natural. JSON object only.

RUSSIAN DESCRIPTION:
"""

# Edit mode: a prompt already exists and the Russian text is a CHANGE REQUEST.
# We modify/augment the current prompt instead of rewriting it from scratch, so
# the user can say «сделай нос покрупнее, брови покустистее» and keep the rest.
EDIT_PROMPT: str = """\
You EDIT an existing ENGLISH prompt for ONE layer of a character-reference
generation pipeline by applying a Russian change request. The layers and concerns:
- face: facial anatomy (shape, nose, lips, eyes, hair, skin, facial marks)
- body: build / proportions, body marks under clothing (NO clothing)
- outfit: clothing only (garments, cut, material, colour)
- expression: a short emotion/mood (e.g. "grim, brooding")
- composition: pose / camera / framing / background
- style: the drawing manner / medium / palette (NOT any character)

The user is editing the "{layer}" layer.

CURRENT ENGLISH PROMPT for the '{layer}' layer:
{current}

Apply the Russian change request below by MODIFYING the current prompt:
- KEEP every detail the request does not touch — do NOT rewrite from scratch or drop things.
- Only add, strengthen, soften or remove what the request actually asks for.
- Keep it compact English, comma-separated where natural.
- If the request mentions things belonging to OTHER layers, put those in "suggestions".

Return STRICTLY a JSON object, no fences:
{
  "text": "the FULL updated ENGLISH prompt for the '{layer}' layer ONLY",
  "suggestions": { "<other_layer_key>": "english prompt for that layer", ... }
}

RUSSIAN CHANGE REQUEST:
"""

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass(slots=True)
class Translation:
    """Result of a layer translation: the layer text + other-layer suggestions."""

    text: str = ""
    suggestions: dict[str, str] = field(default_factory=dict)


def build_translate_prompt(ru_text: str, layer: str, current: str = "") -> str:
    """Compose the translation prompt for ``ru_text`` targeting ``layer``.

    With a non-empty ``current`` prompt, the Russian text is treated as a CHANGE
    REQUEST and the existing prompt is modified in place (edit mode); otherwise a
    fresh prompt is produced from scratch (translate mode). ``.replace`` (not
    ``.format``) is used so the literal JSON braces in the templates are safe.
    """
    if current and current.strip():
        return (
            EDIT_PROMPT.replace("{layer}", layer).replace("{current}", current.strip())
            + ru_text.strip()
        )
    return TRANSLATE_PROMPT.replace("{layer}", layer) + ru_text.strip()


def parse_translation(raw: str) -> Translation:
    """Tolerantly parse the LLM reply; a non-JSON reply becomes plain ``text``."""
    if not raw or not raw.strip():
        return Translation()
    stripped = _FENCE_RE.sub("", raw.strip())
    try:
        parsed = json.loads(stripped)
    except (json.JSONDecodeError, ValueError):
        return Translation(text=stripped)  # not JSON — use the reply as the prompt
    if not isinstance(parsed, dict):
        return Translation(text=stripped)
    suggestions = parsed.get("suggestions")
    clean: dict[str, str] = {}
    if isinstance(suggestions, dict):
        for key in _LAYER_KEYS:
            value = coerce_value(suggestions.get(key))
            if value:
                clean[key] = value
    return Translation(text=coerce_value(parsed.get("text")), suggestions=clean)


def translate_layer(
    ru_text: str,
    layer: str,
    *,
    current: str = "",
    model: str | None = None,
    meter: CostLedger | None = None,
) -> Translation:
    """Translate ``ru_text`` into an English prompt for ``layer`` (+ spillover hints).

    When ``current`` is a non-empty existing prompt, ``ru_text`` is applied as a
    change request that modifies it in place rather than rewriting from scratch.
    Empty input short-circuits (no call). On any API failure ``call_llm`` returns
    ``""`` → empty translation; the caller keeps the field as-is. ``meter`` is
    forwarded so the call's cost is attributed by the caller.
    """
    if not ru_text or not ru_text.strip():
        return Translation()
    prompt = build_translate_prompt(ru_text, layer or "this layer", current)
    raw = call_llm(prompt, model=model, meter=meter)
    return parse_translation(raw)
