"""Outfits phase — one generation step per additional outfit (HLE-733, §5).

Each additional outfit (from the data-screen table) gets a full-length step:
front-full + back-full (simple), plus profile-full when the outfit is *complex*.
A complex outfit also has optional extreme close-up "costume detail" shots.

Layer/ref rules (§3.5):

* Outfit scenes use the canonical full-length scenes (FRONT_FULL / BACK_FULL /
  PROFILE_FULL — *not* the passport profile portrait) as the COMPOSITION
  override, identity refs (style + face + body), and ``outfit_conflict=True``
  (the new costume differs from the clothing on the identity refs).
* Detail shots use only style + this outfit's generated front-full ref (roles
  ``style`` + ``outfit``) — no face/body/expression, since identity is not
  needed, only the costume — and ``outfit_conflict=False`` (the ref *is* the
  target outfit).

The OUTFIT prompt layer is selected by ``active_outfit_id`` (K3 ``_resolve_outfit``,
which ignores ``step_key``), so every generate sets ``active_outfit_id`` to the
target outfit first. ``generate_image`` is imported into ``wizard.generation``
(patched there in tests); this module renders via :func:`render_step_image`.

Approval is gated on the *presence* of the required scene generations, never on
the per-preview "approved" checkboxes (those only skip a scene on regenerate).
"""

from __future__ import annotations

from create_char_passport.gen import (
    GenerationResult,
    Ref,
    SceneId,
    build_prompt_layers,
    effective_composition,
)
from create_char_passport.gen.prompt import to_prompt_layers
from create_char_passport.state import (
    CharacterState,
    CostLedger,
    OutfitDetail,
    OutfitEntry,
    StepRecord,
    outfit_detail_step,
    outfit_step,
)
from create_char_passport.storage import character_asset
from create_char_passport.wizard.generation import identity_refs, render_step_image, style_ref

FULL_LENGTH_HINT: str = "Нужен ПОЛНЫЙ РОСТ без обрезок — вся фигура целиком в кадре."

# Max costume-detail close-ups per complex outfit. The screen pre-builds this
# many cells (Gradio's layout is static), and the add path is capped to match so
# state never holds a detail the UI cannot show or delete.
MAX_OUTFIT_DETAILS: int = 3

# The full-length scenes an outfit step renders, in fixed order. profile_full is
# required only for a complex outfit; see :func:`outfit_scenes`.
_SIMPLE_SCENES: tuple[SceneId, ...] = (SceneId.FRONT_FULL, SceneId.BACK_FULL)
_COMPLEX_SCENES: tuple[SceneId, ...] = (*_SIMPLE_SCENES, SceneId.PROFILE_FULL)

# SceneId -> the OutfitRefs path attribute (and its "_approved" companion).
_SCENE_ATTR: dict[SceneId, str] = {
    SceneId.FRONT_FULL: "front_full",
    SceneId.BACK_FULL: "back_full",
    SceneId.PROFILE_FULL: "profile_full",
}


def outfit_scenes(outfit: OutfitEntry) -> tuple[SceneId, ...]:
    """Required scenes for ``outfit``: front+back (simple), +profile (complex)."""
    return _COMPLEX_SCENES if outfit.complex else _SIMPLE_SCENES


def _scene_filename_key(outfit_id: str, scene_id: SceneId) -> str:
    """Internal per-scene storage key so each scene gets its own ``refs/*.png``.

    The pipeline step key is ``outfit_<id>`` for the whole outfit; the three
    scenes would clobber one file, so each scene renders under a distinct
    synthetic key (e.g. ``outfit_1_front_full``). Used only for file naming.
    """
    return f"{outfit_step(outfit_id)}_{scene_id.value}"


def _require_outfit(state: CharacterState, index: int) -> OutfitEntry:
    """Return ``state.outfits[index]`` or raise ``IndexError`` for a bad index."""
    outfits = state.outfits
    if not 0 <= index < len(outfits):
        msg = f"outfit index out of range: {index}"
        raise IndexError(msg)
    return outfits[index]


def generate_outfit_scene(
    state: CharacterState,
    index: int,
    scene_id: SceneId,
    *,
    meter: CostLedger | None = None,
    model: str | None = None,
) -> GenerationResult:
    """Generate one full-length scene for outfit ``index`` and store its ref.

    Sets ``active_outfit_id`` to this outfit first (the OUTFIT layer is selected
    by it, K3). Identity refs + ``outfit_conflict=True``. On success stores the
    relative path into ``refs.<scene>``, clears that scene's approved flag (a
    fresh generation is unapproved), and — for the front-full shot — writes the
    representative ``outfit_<id>`` step record (drives resume / ``can_advance``).
    Raises ``IndexError`` for a bad index or ``KeyError`` for a non-outfit scene.
    """
    outfit = _require_outfit(state, index)
    attr = _SCENE_ATTR[scene_id]
    state.active_outfit_id = outfit.id
    layers = build_prompt_layers(
        state,
        outfit_step(outfit.id),
        overrides={"composition": effective_composition(state, scene_id)},
    )
    result, relative = render_step_image(
        state,
        _scene_filename_key(outfit.id, scene_id),
        layers,
        identity_refs(state),
        meter=meter,
        model=model,
        outfit_conflict=True,
    )
    if result.ok:
        setattr(outfit.refs, attr, relative)
        setattr(outfit.refs, f"{attr}_approved", False)
        if scene_id is SceneId.FRONT_FULL and relative is not None:
            state.steps[outfit_step(outfit.id)] = StepRecord(
                last_path=relative, prompt_layers=to_prompt_layers(layers)
            )
    return result


def generate_outfit_detail(
    state: CharacterState,
    index: int,
    n: int,
    *,
    meter: CostLedger | None = None,
    model: str | None = None,
) -> GenerationResult:
    """Generate costume-detail close-up ``n`` (1-based) for outfit ``index``.

    Refs are style + this outfit's generated front-full only (roles ``style`` +
    ``outfit``); FACE/BODY/EXPRESSION are blanked (identity not needed, only the
    costume). ``outfit_conflict=False`` (the ref already *is* the target outfit).
    Raises ``IndexError`` for a bad outfit/detail index; returns a failed result
    (no ref stored) when the front-full ref is missing.
    """
    outfit = _require_outfit(state, index)
    if not 1 <= n <= len(outfit.details):
        msg = f"outfit detail index out of range: {n}"
        raise IndexError(msg)
    front = outfit.refs.front_full
    if not front:
        return GenerationResult(
            image_path=None, ok=False, error="Сначала сгенерируй фас-рост этого наряда."
        )
    state.active_outfit_id = outfit.id
    refs: list[Ref] = []
    style = style_ref(state)
    if style is not None:
        refs.append(style)
    front_path = character_asset(state.character_id, front)
    if front_path.is_file():
        refs.append(Ref(path=str(front_path), role="outfit"))
    # COMPOSITION = the close-up preset + the detail's own prompt text (§5: the
    # detail field names which part of the costume to zoom in on).
    composition = effective_composition(state, SceneId.DETAIL_CLOSEUP)
    detail_text = outfit.details[n - 1].prompt.strip()
    if detail_text:
        composition = f"{composition}\n{detail_text}"
    layers = build_prompt_layers(
        state,
        outfit_detail_step(outfit.id, n),
        overrides={"face": "", "body": "", "expression": "", "composition": composition},
    )
    result, relative = render_step_image(
        state,
        f"{outfit_detail_step(outfit.id, n)}",
        layers,
        refs,
        meter=meter,
        model=model,
        outfit_conflict=False,
    )
    if result.ok:
        outfit.details[n - 1].ref = relative
    return result


def add_outfit_detail(state: CharacterState, index: int) -> int:
    """Append an empty costume-detail slot to outfit ``index``; return its 1-based n.

    Capped at :data:`MAX_OUTFIT_DETAILS` (the screen pre-builds that many cells);
    at the cap this is a no-op returning the current count, so state never holds
    a detail with no UI cell.
    """
    outfit = _require_outfit(state, index)
    if len(outfit.details) < MAX_OUTFIT_DETAILS:
        outfit.details.append(OutfitDetail())
    return len(outfit.details)


def delete_outfit_detail(state: CharacterState, index: int, n: int) -> None:
    """Remove costume-detail ``n`` (1-based) from outfit ``index`` (no-op if absent)."""
    outfit = _require_outfit(state, index)
    if 1 <= n <= len(outfit.details):
        del outfit.details[n - 1]


def detail_has_generation(state: CharacterState, index: int, n: int) -> bool:
    """True if detail ``n`` of outfit ``index`` has a generated ref on disk."""
    outfit = _require_outfit(state, index)
    if not 1 <= n <= len(outfit.details):
        return False
    ref = outfit.details[n - 1].ref
    return bool(ref) and character_asset(state.character_id, ref).is_file()


def set_outfit_complex(state: CharacterState, index: int, complex_: bool) -> None:
    """Set outfit ``index`` complexity. Never touches refs.

    Turning *off* only hides the profile (it leaves ``profile_full`` for restore
    and excludes it from the required scenes); turning *on* restores it. Nothing
    is ever auto-deleted (§5).
    """
    _require_outfit(state, index).complex = bool(complex_)


def required_scenes_present(outfit: OutfitEntry) -> bool:
    """True iff every required scene of ``outfit`` has a stored ref path.

    Keyed on path *presence*, never on the per-preview approved flags (§5).
    """
    return all(getattr(outfit.refs, _SCENE_ATTR[scene]) for scene in outfit_scenes(outfit))


def missing_outfit_scenes(state: CharacterState) -> list[str]:
    """Labels of required-but-missing scenes across all outfits (drives the gate)."""
    missing: list[str] = []
    if not state.outfits_enabled:
        return missing
    for outfit in state.outfits:
        label = outfit.prompt.strip() or f"наряд {outfit.id}"
        for scene in outfit_scenes(outfit):
            if not getattr(outfit.refs, _SCENE_ATTR[scene]):
                missing.append(f"{label} — {scene.value}")
    return missing


def approve_outfit(state: CharacterState, index: int) -> bool:
    """Approve outfit ``index`` and make it active. No-op (False) if incomplete.

    Marks every present required scene approved and sets ``active_outfit_id`` to
    this outfit (§5: the outfit becomes active). The ref paths are already the
    canonical refs, so there is no separate path promotion.
    """
    outfit = _require_outfit(state, index)
    if not required_scenes_present(outfit):
        return False
    for scene in outfit_scenes(outfit):
        setattr(outfit.refs, f"{_SCENE_ATTR[scene]}_approved", True)
    state.active_outfit_id = outfit.id
    return True


def all_outfits_approved(state: CharacterState) -> bool:
    """True when the block is off, or every additional outfit has its scenes present."""
    if not state.outfits_enabled:
        return True
    return all(required_scenes_present(outfit) for outfit in state.outfits)


def first_outfit_step(state: CharacterState) -> str | None:
    """Step key of the first additional outfit (the phase entry cursor), or ``None``."""
    return outfit_step(state.outfits[0].id) if state.outfits else None


def current_outfit_index(state: CharacterState) -> int | None:
    """Index of the outfit the cursor (``current_step``) is on, or ``None``.

    The cursor for a costume-detail step (``outfit_<id>_detail_<n>``) still
    resolves to its parent outfit, so the detail block stays on the right outfit.
    """
    step = state.current_step
    if not step:
        return None
    for i, outfit in enumerate(state.outfits):
        prefix = outfit_step(outfit.id)
        if step == prefix or step.startswith(f"{prefix}_detail_"):
            return i
    return None


def adjacent_outfit_step(state: CharacterState, index: int, *, forward: bool) -> str | None:
    """Step key of the next/previous outfit relative to ``index``, or ``None`` at the edge."""
    nxt = index + 1 if forward else index - 1
    return outfit_step(state.outfits[nxt].id) if 0 <= nxt < len(state.outfits) else None


def set_outfit_prompt(state: CharacterState, step_key: str, text: str) -> bool:
    """Write the OUTFIT prompt of the outfit named by ``step_key`` (``outfit_<id>``).

    Used by the AI-assist write-back (HLE-731); returns ``False`` if no outfit
    matches the key (so a stray ``&step&`` marker never creates a phantom outfit).
    """
    for outfit in state.outfits:
        if outfit_step(outfit.id) == step_key:
            outfit.prompt = text.strip()
            return True
    return False


def set_outfit_detail_prompt(state: CharacterState, step_key: str, text: str) -> bool:
    """Write a costume-detail prompt named by ``step_key`` (``outfit_<id>_detail_<n>``)."""
    for outfit in state.outfits:
        for n in range(1, len(outfit.details) + 1):
            if outfit_detail_step(outfit.id, n) == step_key:
                outfit.details[n - 1].prompt = text.strip()
                return True
    return False
