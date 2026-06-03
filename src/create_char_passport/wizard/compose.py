"""Compose default prompt layers from the character trait table via one LLM call.

After a character is extracted/edited into the ``character_table`` (gender, age,
build, hair, eyes, skin, role, details), this turns that table into layer-isolated
English DRAFT prompts for FACE / BODY / OUTFIT and a default base EXPRESSION —
splitting the особые приметы (``details``) into face- vs body-marks. The user can
re-run it on demand («Разобрать по промтам с ИИ»). It only seeds editable drafts;
nothing here is frozen (that happens on the passport step).

Rides the K2 engine (``call_llm``); parsing is tolerant (a broken reply degrades
to empty layers, never raises).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from create_char_passport.gen import call_llm
from create_char_passport.state import CostLedger, coerce_value

COMPOSE_PROMPT: str = """\
You turn a Russian character trait sheet into layer-isolated ENGLISH prompt
drafts for a consistent character-reference image pipeline. Read the Russian
traits and особые приметы faithfully, then write DETAILED, concrete, VISUAL
English prompts — comma-separated descriptor phrases a text-to-image model can
actually render, not vague adjectives. Make implied physical detail explicit
(e.g. old age → wrinkles, grey/thinning hair, age spots; a «воин»/soldier →
weathered skin, muscular build; «полный» → round face, double chin, heavy
frame), but NEVER invent traits that contradict the sheet, and never add a trait
the sheet gives no basis for.

Return STRICTLY a JSON object, no markdown fences, no explanation:
{
  "face": "[FACE] facial anatomy ONLY, detailed: face shape, forehead, eyebrows,
           eyes (shape + colour), nose, lips/mouth, cheekbones, jawline/chin,
           ears, skin (tone + texture), facial hair, hairstyle (length, cut,
           colour, texture), plus face-specific permanent marks (facial scar, eye
           patch, freckles, moles). ~8-18 comma-separated descriptors. NO
           expression/emotion, NO pose, NO clothing, NO background.",
  "body": "[BODY] build / proportions ONLY, detailed: overall physique, apparent
           height, shoulders, frame, musculature or softness, posture, hands,
           plus body-specific permanent marks under clothing (tattoo + its
           placement, body scars, missing limb). NO clothing, NO face, NO pose,
           NO mood.",
  "outfit": "[OUTFIT] base clothing ONLY, detailed: each garment named with its
            cut, fabric/material, colour and trim, plus footwear and worn
            accessories (belt, gloves, cloak). NO anatomy, NO pose, NO
            expression, NO background.",
  "base_emotion": "a short default EXPRESSION in English (e.g. 'grim, brooding'),
            derived from the role / personality. 2-4 words. NO prose."
}

Rules:
- Split особые приметы / "details" across face vs body by what each one is.
- Keep each layer strictly to its own concern; never leak expression into face,
  clothing into body, or anatomy into outfit.
- Faithful first, detailed second: every descriptor must be stated in, or a
  reasonable visual implication of, the sheet. English only.
- If the sheet genuinely has nothing for a layer, use an empty string "".
- The answer is the JSON object only.

CHARACTER TRAIT TABLE (JSON, values may be in Russian):
"""

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)
_LAYER_KEYS: tuple[str, ...] = ("face", "body", "outfit", "base_emotion")


@dataclass(slots=True)
class ComposedLayers:
    """Layer drafts composed from the trait table (all editable, never frozen)."""

    face: str = ""
    body: str = ""
    outfit: str = ""
    base_emotion: str = ""


def build_compose_prompt(table: dict[str, str]) -> str:
    """Compose the full prompt for ``table``."""
    return COMPOSE_PROMPT + json.dumps(table, ensure_ascii=False)


def parse_compose_response(raw: str) -> ComposedLayers:
    """Tolerantly parse the LLM reply into :class:`ComposedLayers` (never raises)."""
    if not raw or not raw.strip():
        return ComposedLayers()
    try:
        parsed = json.loads(_FENCE_RE.sub("", raw.strip()))
    except (json.JSONDecodeError, ValueError):
        return ComposedLayers()
    if not isinstance(parsed, dict):
        return ComposedLayers()
    values = {key: coerce_value(parsed.get(key)) for key in _LAYER_KEYS}
    return ComposedLayers(**values)


def compose_layers(
    table: dict[str, str], *, model: str | None = None, meter: CostLedger | None = None
) -> ComposedLayers:
    """Run the paid compose call for ``table`` and parse the reply.

    An empty table short-circuits (no call). On any API failure ``call_llm``
    returns ``""`` which parses to empty layers — the caller keeps the prior
    drafts. ``meter`` is forwarded so the call's cost is attributed by the caller.
    """
    if not any((table or {}).values()):
        return ComposedLayers()
    raw = call_llm(build_compose_prompt(table), model=model, meter=meter)
    return parse_compose_response(raw)
