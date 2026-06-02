"""LoRA-ready export of a character's golden set (HLE-805, epic HLE-802).

A character's char-LoRA trains on EVERY approved image that depicts it — the
"golden set" (passport angles, base + series emotions, outfit scenes) plus its
dataset expansion (the composition frames). The pipe is: the tool generates the
golden set → the dataset phase expands it into more poses → all of it is handed
to that character's char-LoRA trainer (HLE-804). One bundle per character; new
characters export independently at any time.

This module gathers those images and writes a kohya / ai-toolkit style dataset:
each frame as an image plus a ``.txt`` sidecar holding a CONTENT-ONLY caption
prefixed with a per-character trigger token. Two caption rules keep the captions
training-clean:

* **No STYLE.** Imposing the comic style is the *style-LoRA's* job; captioning
  style words would teach the char-LoRA to reproduce them (layer separation).
* **No generation directives.** The stored ``composition`` layer is the full
  scene-generation prompt (framing + background + a long list of negatives like
  "no text, no panel border"). A trainer reads a caption as what IS present —
  "no text" would teach it to add text — so the verbose composition is replaced
  with a short, clean framing phrase (e.g. "full body, front view").

Captions are also pinned to ground truth: emotion portraits are always shot in
the *base* outfit, so their captions force the base outfit (never the outfit
that happens to be active at export time). Collection is by ref presence, NOT
gated on the ``enabled`` toggles — a generated image whose block the user later
turned off is still a character photo (nothing is auto-deleted, §5), so it ships.
Only images that do NOT show the character are excluded: prop product-shots and
outfit-detail macros (face blanked).

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
from create_char_passport.gen.scenes import SceneId, scene_for_step
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    PASSPORT_STEPS,
    CharacterState,
    PromptLayers,
    StepKind,
    classify_step,
    dataset_step,
    emotion_step,
    outfit_step,
    slugify,
)
from create_char_passport.storage import character_asset, character_dir

# Layers written into the training caption, in order. STYLE is excluded on
# purpose (see module docstring); ``composition`` carries the short clean framing
# substituted by :func:`_clean_framing` (never the verbose generation preset).
CONTENT_LAYERS: tuple[str, ...] = ("face", "body", "outfit", "expression", "composition")

# Short, clean framing phrases per scene — used for the caption instead of the
# verbose ``SCENE_PRESETS`` text (which is full of generation negatives).
_SCENE_FRAMING: dict[SceneId, str] = {
    SceneId.FRONT_PORTRAIT: "portrait, head and shoulders, front view",
    SceneId.FRONT_FULL: "full body, front view",
    SceneId.PROFILE_PORTRAIT: "portrait, head and shoulders, side profile",
    SceneId.BACK_FULL: "full body, back view",
    SceneId.THREE_QUARTER_FULL: "full body, three-quarter view",
    SceneId.PROFILE_FULL: "full body, side profile",
}

# Outfit scene ref attribute -> the framing it adds to the caption (the three
# scenes share one outfit step_key, so the angle is what distinguishes them).
_OUTFIT_SCENES: tuple[tuple[str, str], ...] = (
    ("front_full", "full body, front view"),
    ("back_full", "full body, back view"),
    ("profile_full", "full body, side profile"),
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
    skipped: int = 0
    files: list[Path] = field(default_factory=list)


@dataclass(slots=True)
class _Frame:
    """One approved character image bound for the training set.

    ``framing`` is the short clean composition phrase for the caption (outfit
    scene angle or a dataset pose); ``None`` defers to the scene-derived framing.
    ``expression`` carries the verbatim emotion value (emotion frames only), so
    the caption keeps the exact label instead of de-slugging the step key.
    """

    step_key: str
    rel_path: str
    framing: str | None = None
    expression: str | None = None


def default_trigger(state: CharacterState) -> str:
    """Provisional per-character trigger token (HLE-802 ``<char>_char``).

    Falls back to the character id when the name has no ASCII letters (e.g. a
    Cyrillic-only name slugs to the empty ``"x"`` fallback) so the trigger is at
    least character-scoped rather than the generic ``"x"``.
    """
    slug = slugify(state.name)
    if slug == "x":  # slugify's empty-input fallback — the name carried no ASCII
        slug = slugify(state.character_id)
    return f"{slug}_char"


def content_caption(layers: PromptLayers, trigger: str) -> str:
    """Build a content-only caption: ``trigger`` + non-empty content layers.

    STYLE is never included. Interior whitespace is collapsed so a caption is
    always one line; empty layers are dropped so there are no dangling
    separators. Returns the trigger alone when no content layer is filled.
    """
    parts: list[str] = []
    cleaned_trigger = " ".join(trigger.split())
    if cleaned_trigger:
        parts.append(cleaned_trigger)
    for name in CONTENT_LAYERS:
        value = " ".join((getattr(layers, name, "") or "").split())
        if value:
            parts.append(value)
    return ", ".join(parts)


def _collect_frames(state: CharacterState) -> list[_Frame]:
    """Every approved image that DEPICTS the character, in pipeline order.

    Passport (5 angles) + base emotion + emotion series + outfit scenes +
    dataset compositions — the whole golden set plus its dataset expansion.

    Collection is by REF PRESENCE, deliberately NOT gated on the ``enabled``
    toggles: a generated image that the user later turned the block off for is
    still a character photo and is never auto-deleted (§5), so it belongs in the
    training set ("hand over ALL the character's photos", HLE-802). Only frames
    that do NOT show the character are excluded: props (product shots) and
    outfit-detail macros (close-ups with the face blanked).
    """
    frames: list[_Frame] = []
    for key in PASSPORT_STEPS:
        record = state.steps.get(key)
        if record is not None and record.approved_path:
            frames.append(_Frame(key, record.approved_path))
    base = state.emotions.base_emotion
    if base.ref:
        frames.append(_Frame(BASE_EMOTION_STEP, base.ref, expression=base.value))
    for item in state.emotions.items:
        if item.ref:
            frames.append(_Frame(emotion_step(item.value), item.ref, expression=item.value))
    for outfit in state.outfits:
        for attr, angle in _OUTFIT_SCENES:
            rel = getattr(outfit.refs, attr)
            if rel:
                frames.append(_Frame(outfit_step(outfit.id), rel, framing=angle))
    for idx in range(len(state.dataset_compositions)):
        record = state.steps.get(dataset_step(idx))
        if record is not None and record.approved_path:
            frames.append(
                _Frame(dataset_step(idx), record.approved_path, framing=_dataset_pose(state, idx))
            )
    return frames


def _dataset_pose(state: CharacterState, idx: int) -> str:
    """The user's raw dataset pose for frame ``idx`` (no background directive)."""
    return (
        state.dataset_compositions[idx].strip()
        if 0 <= idx < len(state.dataset_compositions)
        else ""
    )


def _has_content(layers: PromptLayers) -> bool:
    """True if any content (non-STYLE) layer carries text."""
    return any((getattr(layers, name, "") or "").strip() for name in CONTENT_LAYERS)


def _caption_layers(state: CharacterState, step_key: str) -> PromptLayers:
    """Faithful face/body/outfit/expression layers for ``step_key``.

    Uses the stored per-step snapshot when present (passport / outfit front-full
    / dataset persist ``prompt_layers``), else rebuilds from current state. The
    OUTFIT layer is pinned to ground truth: emotion portraits are shot in the
    base outfit, so they force it (never the outfit active at export time); an
    outfit step with no snapshot forces THIS outfit's clothes. The composition
    layer here is ignored — :func:`_frame_caption` always substitutes a clean
    framing phrase.
    """
    record = state.steps.get(step_key)
    if record is not None and _has_content(record.prompt_layers):
        return record.prompt_layers
    overrides: dict[str, str] = {}
    kind = classify_step(step_key)
    if kind in (StepKind.EMOTION, StepKind.BASE_EMOTION):
        overrides["outfit"] = state.base_outfit.prompt
    else:
        for outfit in state.outfits:
            if outfit_step(outfit.id) == step_key and outfit.prompt.strip():
                overrides["outfit"] = outfit.prompt
                break
    return to_prompt_layers(build_prompt_layers(state, step_key, overrides=overrides or None))


def _clean_framing(state: CharacterState, frame: _Frame) -> str:
    """Short framing phrase for the caption (never the verbose scene preset)."""
    if frame.framing is not None:
        return frame.framing
    scene = scene_for_step(frame.step_key)
    return _SCENE_FRAMING.get(scene, "") if scene is not None else ""


def _frame_caption(state: CharacterState, frame: _Frame, trigger: str) -> str:
    """Content-only caption for one frame, with a clean framing phrase.

    The verbatim emotion value (when carried) replaces the de-slugged expression;
    a back view drops the expression entirely, since the face is not visible.
    """
    framing = _clean_framing(state, frame)
    layers = replace(_caption_layers(state, frame.step_key), composition=framing)
    if frame.expression is not None:
        layers = replace(layers, expression=frame.expression)
    if "back view" in framing:
        layers = replace(layers, expression="")
    return content_caption(layers, trigger)


def export_lora_dataset(
    state: CharacterState, out_dir: str | Path, *, trigger: str | None = None
) -> LoraExportResult:
    """Stage every approved character image as ``NNN.png`` + ``NNN.txt`` in ``out_dir``.

    Frames are taken in pipeline order (see :func:`_collect_frames`); each caption
    is content-only (see :func:`content_caption`). Frames whose image is missing
    on disk are skipped and counted in ``LoraExportResult.skipped`` so a partial
    export is distinguishable from a complete one.
    """
    trig = (trigger or default_trigger(state)).strip()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files: list[Path] = []
    written = 0
    skipped = 0
    for frame in _collect_frames(state):
        source = character_asset(state.character_id, frame.rel_path)
        if not source.is_file():
            skipped += 1
            continue
        stem = f"{written:03d}"
        image_dst = out / f"{stem}.png"
        shutil.copyfile(source, image_dst)
        (out / f"{stem}.txt").write_text(_frame_caption(state, frame, trig), encoding="utf-8")
        files.append(image_dst)
        written += 1
    return LoraExportResult(out_dir=out, trigger=trig, count=written, skipped=skipped, files=files)


def export_lora_zip(
    state: CharacterState, *, trigger: str | None = None
) -> tuple[str | None, LoraExportResult]:
    """Stage the golden set under the bucket and zip it for download.

    Returns ``(zip_path, result)``. ``zip_path`` is ``None`` when there is
    nothing approved to export. The staging dir is rebuilt from scratch each call
    so a re-export never mixes in stale frames.
    """
    char_dir = character_dir(state.character_id)
    staging = char_dir / _STAGING_DIRNAME
    if staging.exists():
        shutil.rmtree(staging)
    result = export_lora_dataset(state, staging, trigger=trigger)
    if result.count == 0:
        return None, result
    zip_path = shutil.make_archive(str(char_dir / _ARCHIVE_STEM), "zip", root_dir=str(staging))
    return zip_path, result
