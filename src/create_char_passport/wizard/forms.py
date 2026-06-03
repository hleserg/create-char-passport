"""Pure form <-> state logic for the start and character-data screens.

These functions carry everything the three input screens *do*, with no Gradio
in sight, so they are unit-tested directly: build a character from extracted
traits, read/write the trait table, toggle the optional blocks, add/remove
outfit and prop rows, and list / resume saved characters from the bucket.

Design rules honoured here:

* The user is the source of truth — extraction only seeds an editable draft.
* Optional blocks map to the *exact* state fields the router reads: the
  "Эмоции" checkbox writes ``emotions.enabled`` (nested), while outfits/props
  use the top-level ``*_enabled`` flags (§5 / contract K1 router).
* Outfit / prop ids are bare ordinals so the K1 constructors build clean step
  keys (``outfit_step("1") == "outfit_1"``) without a doubled prefix.
* Editing the row tables preserves a kept row's generated refs/details by
  index (a reloaded character keeps its work; only added rows are fresh).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from create_char_passport.state import (
    CharacterState,
    OutfitEntry,
    PropEntry,
    PropShot,
    blank_state,
    normalize_character_table,
)
from create_char_passport.storage import list_character_ids, load_state
from create_char_passport.wizard.extraction import ExtractedCharacter
from create_char_passport.wizard.props import MAX_PROP_SHOTS
from create_char_passport.wizard.style import apply_style

BASE_OUTFIT_PLACEHOLDER: str = "(set on the passport step)"


# --------------------------------------------------------------------------- #
# Character creation + trait table
# --------------------------------------------------------------------------- #
def character_from_extracted(
    extracted: ExtractedCharacter, *, style_prompt: str = ""
) -> CharacterState:
    """Build a fresh character from an extracted draft (+ optional frozen style).

    Seeds the layer-isolated draft prompts the extraction inferred —
    ``prompt_layers.face`` / ``prompt_layers.body`` and ``base_outfit.prompt`` —
    so the passport step opens pre-filled. These are drafts: fully editable, and
    only frozen later on the passport step (the user is the source of truth).
    """
    state = blank_state(extracted.name)
    state.character_table = normalize_character_table(extracted.table)
    state.prompt_layers.face = extracted.face.strip()
    state.prompt_layers.body = extracted.body.strip()
    state.base_outfit.prompt = extracted.outfit.strip()
    if style_prompt.strip():
        apply_style(state, style_prompt)
    return state


def table_from_state(state: CharacterState) -> dict[str, str]:
    """The character's trait table, fully keyed and cleaned for the form."""
    return normalize_character_table(state.character_table)


def apply_table(state: CharacterState, table: dict[str, str]) -> None:
    """Write edited trait values back onto the character (user is truth)."""
    state.character_table = normalize_character_table(table)


def base_outfit_display(state: CharacterState) -> str:
    """Read-only base-outfit text, or the placeholder before the passport step."""
    return state.base_outfit.prompt.strip() or BASE_OUTFIT_PLACEHOLDER


# --------------------------------------------------------------------------- #
# Emotions + base emotion
# --------------------------------------------------------------------------- #
def set_emotions_enabled(state: CharacterState, enabled: bool) -> None:
    """Toggle the "Эмоции" block — writes the nested ``emotions.enabled``."""
    state.emotions.enabled = bool(enabled)


def emotion_rows(state: CharacterState) -> list[list[str]]:
    """Display rows for the 3-emotion table: ``[value, ref-or-dash]``."""
    return [[item.value, item.ref or "—"] for item in state.emotions.items]


def set_base_emotion(state: CharacterState, enabled: bool, value: str) -> None:
    """Store the base-emotion toggle + value (the K3 builder applies the rule)."""
    state.emotions.base_emotion.enabled = bool(enabled)
    state.emotions.base_emotion.value = value.strip()


# --------------------------------------------------------------------------- #
# Outfit + prop row tables
# --------------------------------------------------------------------------- #
def _next_ordinal_id(existing: Iterable[str]) -> str:
    """Smallest unused positive ordinal as a string (stable across removals)."""
    used = {int(x) for x in existing if str(x).isdigit()}
    n = 1
    while n in used:
        n += 1
    return str(n)


def set_outfits_enabled(state: CharacterState, enabled: bool) -> None:
    """Toggle the "Дополнительные наряды" block (top-level flag)."""
    state.outfits_enabled = bool(enabled)


def outfit_rows(state: CharacterState) -> list[list[object]]:
    """Editable outfit rows: ``[prompt, complex]`` (refs come in the outfit phase)."""
    return [[o.prompt, o.complex] for o in state.outfits]


def sync_outfits(state: CharacterState, rows: Iterable[Iterable[object]]) -> None:
    """Rebuild ``state.outfits`` from edited ``[prompt, complex]`` rows.

    Kept rows (matched by position) preserve their id, generated refs and
    detail shots; new rows get a fresh ordinal id. Blank-prompt trailing rows
    that Gradio's dataframe appends are dropped.
    """
    cleaned = [(_cell_str(r, 0), _cell_bool(r, 1)) for r in _as_rows(rows)]
    cleaned = [(prompt, complex_) for prompt, complex_ in cleaned if prompt]
    previous = list(state.outfits)
    rebuilt: list[OutfitEntry] = []
    assigned: set[str] = set()
    for idx, (prompt, complex_) in enumerate(cleaned):
        if idx < len(previous):
            entry = previous[idx]
            entry.prompt = prompt
            entry.complex = complex_
        else:
            entry = OutfitEntry(id=_next_ordinal_id(assigned), prompt=prompt, complex=complex_)
        assigned.add(entry.id)
        rebuilt.append(entry)
    state.outfits = rebuilt


def set_props_enabled(state: CharacterState, enabled: bool) -> None:
    """Toggle the "Предметы" block (top-level flag)."""
    state.props_enabled = bool(enabled)


def prop_rows(state: CharacterState) -> list[list[object]]:
    """Editable prop rows: ``[name]`` (shots come in the props phase)."""
    return [[p.name] for p in state.props]


def sync_props(state: CharacterState, rows: Iterable[Iterable[object]]) -> None:
    """Rebuild ``state.props`` from edited ``[name, shots?]`` rows.

    Existing props are matched by position and keep their shots untouched (so the
    per-shot ``what``/prompt/image data built on the props step is never
    truncated — the optional ``shots`` count only seeds NEW props). A new prop is
    born with its requested shot count, clamped to ``1..MAX_PROP_SHOTS``.
    """
    parsed = [(_cell_str(r, 0), _cell_int(r, 1)) for r in _as_rows(rows)]
    parsed = [(name, shots) for name, shots in parsed if name]
    previous = list(state.props)
    rebuilt: list[PropEntry] = []
    assigned: set[str] = set()
    for idx, (name, shots) in enumerate(parsed):
        if idx < len(previous):
            entry = previous[idx]
            entry.name = name
        else:
            # §5: "1 кадр по умолчанию", up to MAX_PROP_SHOTS. The anketa picker
            # may pre-seed more for a brand-new prop; existing props are never
            # shrunk here (that would drop generated per-shot data).
            n = max(1, min(shots or 1, MAX_PROP_SHOTS))
            entry = PropEntry(
                id=_next_ordinal_id(assigned), name=name, shots=[PropShot() for _ in range(n)]
            )
        assigned.add(entry.id)
        rebuilt.append(entry)
    state.props = rebuilt


def _as_rows(rows: Iterable[Iterable[object]] | None) -> list[list[object]]:
    """Coerce a dataframe-ish value (list of rows) into a list of lists."""
    if not rows:
        return []
    return [list(r) for r in rows]


def _cell_str(row: list[object], idx: int) -> str:
    """Read a cell as a trimmed string ("" when missing/None)."""
    if idx >= len(row) or row[idx] is None:
        return ""
    return str(row[idx]).strip()


def _cell_int(row: list[object], idx: int) -> int:
    """Read a cell as a non-negative int (0 when missing/None/unparseable)."""
    if idx >= len(row) or row[idx] is None:
        return 0
    try:
        return max(0, int(float(str(row[idx]).strip())))
    except (TypeError, ValueError):
        return 0


def _cell_bool(row: list[object], idx: int) -> bool:
    """Read a cell as a boolean, tolerating dataframe string values."""
    if idx >= len(row):
        return False
    value = row[idx]
    if isinstance(value, str):
        return value.strip().casefold() in {"true", "yes", "1", "✓"}
    return bool(value)


# --------------------------------------------------------------------------- #
# Saved-character list + resume (start screen)
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class SavedCharacter:
    """One row of the "saved characters" list read from the bucket."""

    character_id: str
    name: str
    in_progress: bool

    @property
    def status(self) -> str:
        """Human-readable pipeline status."""
        return "in progress" if self.in_progress else "ready"


def saved_characters(*, root: Path | None = None) -> list[SavedCharacter]:
    """Every character folder in the bucket with a readable ``state.json``.

    ``current_step`` set -> the pipeline is unfinished ("in progress"); empty
    (cleared on completion) -> "ready". Unreadable folders are skipped, never
    raised, so a single corrupt save can't blank the whole list.
    """
    rows: list[SavedCharacter] = []
    for character_id in list_character_ids(root=root):
        try:
            state = load_state(character_id, root=root)
        except (ValueError, OSError, KeyError):
            # A single unreadable / malformed save must not blank the list.
            continue
        if state is None:
            continue
        rows.append(
            SavedCharacter(
                character_id=state.character_id,
                name=state.name or state.character_id,
                in_progress=bool(state.current_step),
            )
        )
    return rows
