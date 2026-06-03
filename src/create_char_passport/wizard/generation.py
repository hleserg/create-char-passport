"""Shared generation helpers for the optional phases (emotions / outfits / props / dataset).

Two pieces every post-passport phase reuses:

* :func:`identity_refs` — the character's role references (STYLE image + the
  approved FACE and BODY passport shots), attached so identity stays consistent
  (§3.5). The passport phase has its own per-frame schedule and does not use this.
* :func:`render_step_image` — the robust generate→archive→move flow: render to a
  pending file, and only on success archive the previous frame to ``rejected/``
  (never overwrite, §5) and move the new one into ``refs/<step_key>.png``. A
  failed call leaves the previous frame and the prompt untouched.

``generate_image`` is imported at module level so tests patch it here.
"""

from __future__ import annotations

from create_char_passport.gen import GenerationResult, Ref, generate_image
from create_char_passport.gen.engine import RefRole
from create_char_passport.state import CharacterState, CostLedger
from create_char_passport.storage import (
    REFS_DIR,
    archive_to_rejected,
    character_asset,
    character_dir,
)


def style_ref(state: CharacterState) -> Ref | None:
    """The STYLE reference image (role ``style``), or ``None`` if not set / missing."""
    if not state.style_ref:
        return None
    path = character_asset(state.character_id, state.style_ref)
    return Ref(path=str(path), role="style") if path.is_file() else None


def approved_step_ref(state: CharacterState, step_key: str, role: RefRole) -> Ref | None:
    """Reference built from a step's approved shot (role ``role``), or ``None``.

    ``None`` when the step is unapproved or its file is absent (defensive against
    a half-finished or hand-edited state).
    """
    record = state.steps.get(step_key)
    if record is None or not record.approved_path:
        return None
    path = character_asset(state.character_id, record.approved_path)
    return Ref(path=str(path), role=role) if path.is_file() else None


def identity_refs(state: CharacterState) -> list[Ref]:
    """Role refs that carry identity into a post-passport generation: style + face + body.

    Order is canonical (style first); each is included only when it resolves to a
    real file. After the passport phase both passport_face and passport_body are
    approved, so face + body are present; style depends on the style step.
    """
    candidates = (
        style_ref(state),
        approved_step_ref(state, "passport_face", "face"),
        approved_step_ref(state, "passport_body", "body"),
    )
    return [ref for ref in candidates if ref is not None]


def render_step_image(
    state: CharacterState,
    step_key: str,
    layers: dict[str, str],
    refs: list[Ref],
    *,
    meter: CostLedger | None = None,
    model: str | None = None,
    outfit_conflict: bool = False,
) -> tuple[GenerationResult, str | None]:
    """Render ``step_key`` to ``refs/<step_key>.png`` with the robust pending flow.

    Returns ``(result, relative_path)``. On failure ``relative_path`` is ``None``
    and the previous frame (if any) is untouched. On success the previous frame
    is archived to ``rejected/`` and the new one is moved into place; the returned
    relative path is what callers store in state (e.g. ``items[].ref``).
    """
    char_dir = character_dir(state.character_id)
    out = char_dir / REFS_DIR / f"{step_key}.png"
    pending = out.with_name(f"{out.name}.pending")
    result = generate_image(
        layers,
        refs,
        outfit_conflict=outfit_conflict,
        output_path=pending,
        model=model,
        meter=meter,
    )
    if not result.ok:
        pending.unlink(missing_ok=True)
        return result, None
    if out.exists():
        archive_to_rejected(char_dir, step_key, out)
    pending.replace(out)
    ok = GenerationResult(
        image_path=str(out),
        ok=True,
        error=None,
        usage=result.usage,
        image_bytes=result.image_bytes,
    )
    return ok, f"{REFS_DIR}/{step_key}.png"
