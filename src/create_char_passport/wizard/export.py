"""LoRA-ready export of the approved dataset (HLE-805, epic HLE-802).

Walks the approved dataset frames and writes a kohya / ai-toolkit style dataset:
each frame as an image plus a ``.txt`` sidecar holding a CONTENT-ONLY caption —
the six prompt layers minus ``STYLE`` — prefixed with a per-character trigger
token. Style is deliberately never captioned: imposing the comic style is the
*style-LoRA's* job, and captioning style words would teach the char-LoRA to
reproduce them (layer separation, HLE-802).

The caption *format* and the trigger *token* are PROVISIONAL defaults from the
HLE-802 contract; they must ultimately match whatever the char-LoRA tooling
expects. They are isolated in :data:`CONTENT_LAYERS`, :func:`content_caption` and
:func:`default_trigger` so pinning them to the trial LoRA later is a one-line
change, not a refactor.
"""

# PLAYBOOK-START
# id: provisional-default-isolation
# status: draft
# title: Isolate not-yet-locked cross-component defaults behind one function
# body: >
#   When a value (here: caption format + trigger token) must match an external
#   component that does not exist yet, build the mechanism now but keep the
#   guessed value behind a single function/constant so it is a one-line change
#   to pin later — never thread the guess through call sites. Ship the invariant
#   plumbing; defer locking the coupled constant.
# substitution-test: passes (no project nouns once "caption/trigger" are removed)
# PLAYBOOK-END

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from create_char_passport.state import (
    CharacterState,
    PromptLayers,
    dataset_step,
    slugify,
)
from create_char_passport.storage import character_asset, character_dir

# Layers written into the training caption, in order. STYLE is excluded on
# purpose (see module docstring); EXPRESSION/COMPOSITION carry pose + framing.
CONTENT_LAYERS: tuple[str, ...] = ("face", "body", "outfit", "expression", "composition")

# Where the staged dataset + its archive land inside the character bucket.
_STAGING_DIRNAME: str = "lora_export"
_ARCHIVE_STEM: str = "lora_dataset"


@dataclass(slots=True)
class LoraExportResult:
    """Outcome of staging the LoRA dataset on disk."""

    out_dir: Path
    trigger: str
    count: int
    files: list[Path] = field(default_factory=list)


def default_trigger(state: CharacterState) -> str:
    """Provisional per-character trigger token (HLE-802 ``<char>_char``)."""
    base = state.name.strip() or state.character_id
    return f"{slugify(base)}_char"


def content_caption(layers: PromptLayers, trigger: str) -> str:
    """Build a content-only caption: ``trigger`` + non-empty content layers.

    STYLE is never included. Empty layers are dropped so the caption never
    carries dangling separators. Returns the trigger alone when no content layer
    is filled (still a valid one-token caption).
    """
    parts: list[str] = []
    cleaned_trigger = trigger.strip()
    if cleaned_trigger:
        parts.append(cleaned_trigger)
    for name in CONTENT_LAYERS:
        value = (getattr(layers, name, "") or "").strip()
        if value:
            parts.append(value)
    return ", ".join(parts)


def export_lora_dataset(
    state: CharacterState, out_dir: str | Path, *, trigger: str | None = None
) -> LoraExportResult:
    """Stage every approved dataset frame as ``NNN.png`` + ``NNN.txt`` in ``out_dir``.

    Each caption is the frame's stored ``prompt_layers`` rendered content-only
    (see :func:`content_caption`). Frames are taken in composition order; frames
    that were never approved (or whose image is missing on disk) are skipped.
    """
    trig = (trigger or default_trigger(state)).strip()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    written = 0
    for idx in range(len(state.dataset_compositions)):
        record = state.steps.get(dataset_step(idx))
        if record is None or not record.approved_path:
            continue
        source = character_asset(state.character_id, record.approved_path)
        if not source.is_file():
            continue
        stem = f"{written:03d}"
        image_dst = out / f"{stem}.png"
        shutil.copyfile(source, image_dst)
        (out / f"{stem}.txt").write_text(
            content_caption(record.prompt_layers, trig), encoding="utf-8"
        )
        files.append(image_dst)
        written += 1
    return LoraExportResult(out_dir=out, trigger=trig, count=written, files=files)


def export_lora_zip(state: CharacterState, *, trigger: str | None = None) -> tuple[str | None, int]:
    """Stage the dataset under the bucket and zip it for download.

    Returns ``(zip_path, count)``. ``(None, 0)`` when there is nothing approved
    to export. The staging dir is rebuilt from scratch each call so a re-export
    never mixes in stale frames.
    """
    char_dir = character_dir(state.character_id)
    staging = char_dir / _STAGING_DIRNAME
    if staging.exists():
        shutil.rmtree(staging)
    result = export_lora_dataset(state, staging, trigger=trigger)
    if result.count == 0:
        return None, 0
    zip_path = shutil.make_archive(str(char_dir / _ARCHIVE_STEM), "zip", root_dir=str(staging))
    return zip_path, result.count
