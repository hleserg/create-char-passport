"""Character extraction — the first AI input step (§4 "извлечение персонажей").

The user pastes a story; one paid LLM call returns the acting characters
*with their traits* (not just names). We send a strict-JSON prompt, then parse
**tolerantly**: a clean JSON array is mapped straight onto
``character_table``; a broken reply degrades to a bare name list (the user
fills the rest in by hand) and never raises — a malformed LLM response must
not take the start screen down (DoD).

The LLM call itself rides the K2 engine (``call_llm``) so cost-counting stays
single-sited; everything else here is pure and unit-tested without a network.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from create_char_passport.gen import call_llm
from create_char_passport.state import (
    CHARACTER_TABLE_KEYS,
    coerce_value,
    normalize_character_table,
)

# The model is told to emit STRICT JSON — but we never trust that, see parsing.
EXTRACTION_PROMPT: str = """\
You extract the acting characters from a work of fiction for a reference-image
generation pipeline. You are given the text. Return STRICTLY a JSON array, with
no markdown fences and no explanation.

Each element is one character (a person/creature that actually acts in the text):
{
  "name":   "name or a stable designation (e.g. 'the old fisherman')",
  "gender": "male | female | other | null",
  "age":    "age estimate from the text ('around 30', 'an old man') or null",
  "build":  "physique if described ('powerful, stocky') or null",
  "hair":   "hair colour and type / beard or null",
  "eyes":   "eye colour or null",
  "skin":   "skin tone or null",
  "role":   "role / occupation / status (warrior, slave, noble) or null",
  "details":"other STABLE outward marks in one line: scars, tattoos, injuries,
             distinctive features; null if none",
  "face":   "DRAFT [FACE] prompt — ENGLISH, anatomy ONLY: face shape, nose, lips,
             eyes, hair, skin. NO expression/emotion, pose, clothing or background.
             null if nothing",
  "body":   "DRAFT [BODY] prompt — ENGLISH, build/proportions + STABLE marks under
             clothing (scars, tattoos). NO clothing. null if nothing",
  "outfit": "DRAFT base-outfit [OUTFIT] prompt — ENGLISH, clothing only: garments,
             cut, material, colour. NO anatomy/pose/expression/background. null if nothing"
}

Rules:
- Do NOT invent. If a trait is not in the text -> strictly null.
- Do not confuse TEMPORARY things (a scene's clothing, pose, emotion) with a
  PERMANENT mark. In details put only stable outward features, not momentary ones.
- face / body / outfit are short ENGLISH prompt drafts kept STRICTLY layer-isolated
  (anatomy / physique / clothing) — the user refines and freezes them later. Never
  put an expression or emotion in face; never put clothing in body; never put
  anatomy, pose or background in outfit. null any draft not supported by the text.
- Unnamed walk-on characters with no distinctive marks may be omitted.
- Keep table value language as in the source text; face/body/outfit drafts are ENGLISH.
- The answer is the JSON array only.

TEXT:
"""

_NAME_RE = re.compile(r'"name"\s*:\s*"((?:[^"\\]|\\.)+)"')
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


@dataclass(slots=True)
class ExtractedCharacter:
    """One extracted character — a name, a trait table, and draft prompt layers.

    ``face`` / ``body`` / ``outfit`` are layer-isolated English DRAFT prompts the
    extraction may infer from the text; they seed ``prompt_layers.face/body`` and
    ``base_outfit.prompt`` and are fully editable (frozen only on the passport step).
    """

    name: str
    table: dict[str, str] = field(default_factory=dict)
    face: str = ""
    body: str = ""
    outfit: str = ""


def build_extraction_prompt(text: str) -> str:
    """Compose the full extraction prompt for ``text``."""
    return f"{EXTRACTION_PROMPT}{text.strip()}"


def _strip_fences(raw: str) -> str:
    """Drop a leading/trailing ```` ```json ```` fence if the model added one."""
    return _FENCE_RE.sub("", raw.strip())


def _from_json(raw: str) -> list[ExtractedCharacter] | None:
    """Strict path: parse a JSON array of objects, or ``None`` if shape is wrong."""
    try:
        parsed = json.loads(_strip_fences(raw))
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, list):
        return None
    characters: list[ExtractedCharacter] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = coerce_value(item.get("name"))
        if not name:
            continue
        table = normalize_character_table({k: item.get(k) for k in CHARACTER_TABLE_KEYS})
        characters.append(
            ExtractedCharacter(
                name=name,
                table=table,
                face=coerce_value(item.get("face")),
                body=coerce_value(item.get("body")),
                outfit=coerce_value(item.get("outfit")),
            )
        )
    return characters


def _names_fallback(raw: str) -> list[ExtractedCharacter]:
    """Salvage just the names from a broken reply (empty tables, user fills in)."""
    seen: set[str] = set()
    characters: list[ExtractedCharacter] = []
    for match in _NAME_RE.finditer(raw):
        name = coerce_value(match.group(1))
        if name and name not in seen:
            seen.add(name)
            characters.append(ExtractedCharacter(name=name, table=normalize_character_table(None)))
    return characters


def parse_extraction_response(raw: str) -> list[ExtractedCharacter]:
    """Tolerantly parse an LLM extraction reply into characters.

    Order of attempts: clean JSON array -> name-only salvage from the raw text
    -> empty list. Never raises, so a malformed reply cannot crash the screen.
    """
    if not raw or not raw.strip():
        return []
    via_json = _from_json(raw)
    if via_json:
        return via_json
    return _names_fallback(raw)


def extract_characters(text: str, *, model: str | None = None) -> list[ExtractedCharacter]:
    """Run the paid extraction call for ``text`` and parse the reply.

    Empty input short-circuits (no call). On any API failure ``call_llm``
    returns ``""`` which parses to an empty list — the caller surfaces a
    "nothing found / try again" notice rather than an error.
    """
    if not text or not text.strip():
        return []
    raw = call_llm(build_extraction_prompt(text), model=model)
    return parse_extraction_response(raw)
