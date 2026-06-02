"""LoRA-ready export of a character's golden set (HLE-805, epic HLE-802).

A character's char-LoRA trains on EVERY approved image that depicts it — the
"golden set" (passport angles, base + series emotions, outfit scenes) plus its
dataset expansion (the composition frames). The pipe is: the tool generates the
golden set → the dataset phase expands it into more poses → all of it is handed
to that character's char-LoRA trainer (HLE-804). One bundle per character; new
characters export independently at any time.

This module gathers those images and writes a kohya / ai-toolkit style dataset:
each frame as an image plus a ``.txt`` sidecar holding a CONTENT-ONLY caption —
the six prompt layers minus ``STYLE`` — prefixed with a per-character trigger
token. Style is deliberately never captioned: imposing the comic style is the
*style-LoRA's* job, and captioning style words would teach the char-LoRA to
reproduce them (layer separation, HLE-802).

Images that do NOT show the character are excluded: prop product-shots (no
character at all) and outfit-detail macros (close-ups with the face blanked).

The caption *format* and the trigger *token* are PROVISIONAL defaults from the
HLE-802 contract; they must ultimately match whatever the char-LoRA tooling
expects. They are isolated in :data:`CONTENT_LAYERS`, :func:`content_caption`
and :func:`default_trigger` so pinning them to the trial LoRA later is a
one-line change, not a refactor.
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
from dataclasses import dataclass, field, replace
from pathlib import Path

from create_char_passport.gen import build_prompt_layers
from create_char_passport.gen.prompt import to_prompt_layers
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    PASSPORT_STEPS,
    CharacterState,
    PromptLayers,
    dataset_step,
    emotion_step,
    outfit_step,
    slugify,
)
from create_char_passport.storage import character_asset, character_dir

# Layers written into the training caption, in order. STYLE is excluded on
# purpose (see module docstring); EXPRESSION/COMPOSITION carry pose + framing.
CONTENT_LAYERS: tuple[str, ...] = ("face", "body", "outfit", "expression", "composition")

# Outfit scene ref attribute -> the framing it adds to the caption (the three
# scenes share one outfit step_key, so the angle is what distinguishes them).
_OUTFIT_SCENES: tuple[tuple[str, str], ...] = (
    ("front_full", "full body, front view"),
    ("back_full", "full body, back view"),
    ("profile_full", "full body, profile view"),
)

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


@dataclass(slots=True)
class _Frame:
    """One approved character image bound for the training set."""

    step_key: str
    rel_path: str
    composition_override: str | None = None


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


def _collect_frames(state: CharacterState) -> list[_Frame]:
    """Every approved image that DEPICTS the character, in pipeline order.

    Passport (5 angles) + base emotion + emotion series + outfit scenes +
    dataset compositions — the whole golden set plus its dataset expansion.
    Props (product shots with NO character) and outfit-detail macros (close-ups
    with the face blanked) are excluded: captioning images without the character
    would teach the char-LoRA the wrong thing.
    """
    frames: list[_Frame] = []
    for key in PASSPORT_STEPS:
        record = state.steps.get(key)
        if record is not None and record.approved_path:
            frames.append(_Frame(key, record.approved_path))
    base = state.emotions.base_emotion
    if base.ref:
        frames.append(_Frame(BASE_EMOTION_STEP, base.ref))
    for item in state.emotions.items:
        if item.ref:
            frames.append(_Frame(emotion_step(item.value), item.ref))
    for outfit in state.outfits:
        for attr, angle in _OUTFIT_SCENES:
            rel = getattr(outfit.refs, attr)
            if rel:
                frames.append(_Frame(outfit_step(outfit.id), rel, composition_override=angle))
    for idx in range(len(state.dataset_compositions)):
        record = state.steps.get(dataset_step(idx))
        if record is not None and record.approved_path:
            frames.append(_Frame(dataset_step(idx), record.approved_path))
    return frames


def _has_content(layers: PromptLayers) -> bool:
    """True if any content (non-STYLE) layer carries text."""
    return any((getattr(layers, name, "") or "").strip() for name in CONTENT_LAYERS)


def _caption_layers(state: CharacterState, step_key: str) -> PromptLayers:
    """Faithful content layers for ``step_key``.

    Uses the stored per-step snapshot when present (passport / outfit front-full
    / dataset persist ``prompt_layers``), else rebuilds from current state
    (emotions store only a ref). For an outfit step with no snapshot (e.g. only a
    back / profile scene was generated), THIS outfit's clothes are forced —
    otherwise the K3 builder would caption the *active* outfit, not this one.
    """
    record = state.steps.get(step_key)
    if record is not None and _has_content(record.prompt_layers):
        return record.prompt_layers
    overrides: dict[str, str] = {}
    for outfit in state.outfits:
        if outfit_step(outfit.id) == step_key and outfit.prompt.strip():
            overrides["outfit"] = outfit.prompt
            break
    return to_prompt_layers(build_prompt_layers(state, step_key, overrides=overrides or None))


def _frame_caption(state: CharacterState, frame: _Frame, trigger: str) -> str:
    """Content-only caption for one frame, with the outfit scene angle applied."""
    layers = _caption_layers(state, frame.step_key)
    if frame.composition_override is not None:
        layers = replace(layers, composition=frame.composition_override)
    return content_caption(layers, trigger)


def export_lora_dataset(
    state: CharacterState, out_dir: str | Path, *, trigger: str | None = None
) -> LoraExportResult:
    """Stage every approved character image as ``NNN.png`` + ``NNN.txt`` in ``out_dir``.

    Frames are taken in pipeline order (see :func:`_collect_frames`); each caption
    is content-only (see :func:`content_caption`). Frames whose image is missing
    on disk are skipped.
    """
    trig = (trigger or default_trigger(state)).strip()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    written = 0
    for frame in _collect_frames(state):
        source = character_asset(state.character_id, frame.rel_path)
        if not source.is_file():
            continue
        stem = f"{written:03d}"
        image_dst = out / f"{stem}.png"
        shutil.copyfile(source, image_dst)
        (out / f"{stem}.txt").write_text(_frame_caption(state, frame, trig), encoding="utf-8")
        files.append(image_dst)
        written += 1
    return LoraExportResult(out_dir=out, trigger=trig, count=written, files=files)


def export_lora_zip(state: CharacterState, *, trigger: str | None = None) -> tuple[str | None, int]:
    """Stage the golden set under the bucket and zip it for download.

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
