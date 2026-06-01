"""Passport phase — the 5 canonical identity frames (HLE-728, §4/§5).

The passport set is the core of a character's identity: five mandatory frames
generated and approved in a fixed order (contract K1
:data:`~create_char_passport.state.PASSPORT_STEPS`)::

    passport_face → passport_body → passport_profile → passport_back → passport_3q

The first two are the *base passport*: approving frame 1 freezes ``[FACE]`` and
makes the shot the **face reference** (role ``face``); approving frame 2 freezes
``[BODY]`` + the base outfit (``base_outfit.frozen``) and makes the shot the
**body reference** (role ``body``). From frame 2 on, every generation attaches
those role references (§3.5); the remaining three frames are mandatory coverage
but are NOT attached as references.

This module is the Gradio-free logic: it owns the per-frame metadata, the
reference schedule, the robust generate→archive flow, the freeze rules, the
soft regeneration cascade (§5), and intra-phase navigation. The screens layer
(:mod:`create_char_passport.screens`) wires thin handlers on top of it.

COMPOSITION text is NOT authored here — it comes from the canonical scene
registry via :func:`~create_char_passport.gen.build_step_overrides` (HLE-749).
``generate_image`` is imported at module level so tests patch it in place.
"""

from __future__ import annotations

from create_char_passport.gen import (
    GenerationResult,
    Ref,
    build_prompt_layers,
    build_step_overrides,
    generate_image,
)
from create_char_passport.gen.engine import RefRole
from create_char_passport.gen.prompt import to_prompt_layers
from create_char_passport.state import (
    PASSPORT_STEPS,
    CharacterState,
    CostLedger,
    StepRecord,
)
from create_char_passport.storage import (
    REFS_DIR,
    archive_to_rejected,
    character_asset,
    character_dir,
)

# Frames whose approved shot is attached as a role reference downstream (§4):
# only the first two ("base passport") are crepted as references.
_REF_FRAMES: frozenset[str] = frozenset({"passport_face", "passport_body"})

# Which prompt layers the user may edit on each frame. FACE is cranked only on
# frame 1, BODY only on frame 2; the base OUTFIT is entered/tuned across both;
# frames 3-5 edit nothing (FACE/BODY/OUTFIT are frozen, EXPRESSION is forced
# neutral by K3, COMPOSITION is the fixed scene preset).
_EDITABLE_LAYERS: dict[str, frozenset[str]] = {
    "passport_face": frozenset({"face", "outfit"}),
    "passport_body": frozenset({"body", "outfit"}),
    "passport_profile": frozenset(),
    "passport_back": frozenset(),
    "passport_3q": frozenset(),
}

# Russian UI strings (verbatim from plan/proekt_zametki.md §5). User-facing
# language on the wizard is Russian (cf. the cost banner); these are spec text.
FRAME_TITLES: dict[str, str] = {
    "passport_face": "Кадр 1/5 — Фас-портрет",
    "passport_body": "Кадр 2/5 — Фас, полный рост",
    "passport_profile": "Кадр 3/5 — Профиль-портрет",
    "passport_back": "Кадр 4/5 — Спина, полный рост",
    "passport_3q": "Кадр 5/5 — 3/4, полный рост",
}

FRAME_CRITERIA: dict[str, str] = {
    "passport_face": "Чёткий фас, лицо смотрит прямо в камеру, head & shoulders.",
    "passport_body": (
        "Полный рост БЕЗ обрезок (от волос до обуви целиком в кадре), фас, стопы на земле."
    ),
    "passport_profile": (
        "Строгий профиль 90°, видна только одна сторона лица (only one eye visible), "
        "head & shoulders."
    ),
    "passport_back": (
        "Полный рост без обрезок, вид со спины, видны затылок/причёска/спина/одежда сзади."
    ),
    "passport_3q": "Полный рост без обрезок, полуоборот (3/4), стопы на земле.",
}

NOTICE: str = (
    "Это базовый кадр для идентичности персонажа. Важно, чтобы он соответствовал "
    "критериям ниже — от него зависит весь дальнейший набор."
)

COMMON_CRITERIA: str = (
    "Общее для всех 5 кадров: нейтральное выражение (принудительно neutral); ровный "
    "серый фон; мягкий равномерный студийный свет; без рамок, надписей, реплик, плашек "
    "и артефактов; без посторонних объектов и людей."
)

FACE_BODY_HINT: str = (
    "Только анатомия и физические приметы: форма лица, нос, губы, глаза, волосы, кожа, "
    "телосложение, шрамы/тату/особые приметы. ЗАПРЕЩЕНО писать сюда выражения лица, "
    "эмоции, состояния, позы, одежду, фон — это другие слои (EXPRESSION / OUTFIT / "
    "COMPOSITION)."
)

CASCADE_WARNING: str = (
    "⚠️ Базовый паспортный кадр (лицо/тело) был перегенерён — этот кадр мог разъехаться. "
    "Проверь его и при необходимости перегенери."
)


def _require_passport(step_key: str) -> None:
    """Guard: raise ``ValueError`` unless ``step_key`` names a passport frame."""
    if step_key not in PASSPORT_STEPS:
        msg = f"not a passport step: {step_key!r}"
        raise ValueError(msg)


def passport_index(step_key: str) -> int:
    """0-based position of ``step_key`` in the canonical passport order."""
    _require_passport(step_key)
    return PASSPORT_STEPS.index(step_key)


def is_ref_frame(step_key: str) -> bool:
    """True for the two base-passport frames whose shot becomes a role reference."""
    return step_key in _REF_FRAMES


def editable_layers(step_key: str) -> frozenset[str]:
    """Prompt layers the user may edit on ``step_key`` (others are read-only)."""
    _require_passport(step_key)
    return _EDITABLE_LAYERS[step_key]


def frame_title(step_key: str) -> str:
    """Human heading for ``step_key`` (e.g. ``"Кадр 1/5 — Фас-портрет"``)."""
    _require_passport(step_key)
    return FRAME_TITLES[step_key]


def frame_criterion(step_key: str) -> str:
    """Per-frame framing criterion text for ``step_key`` (plan §5)."""
    _require_passport(step_key)
    return FRAME_CRITERIA[step_key]


def first_pending_passport(state: CharacterState) -> str | None:
    """Earliest passport frame flagged ``need_regen``, or ``None``.

    The passport screen's entry gate (§5): a frame the user must redo after an
    accepted AI edit pulls them back to it before they can move on.
    """
    for key in PASSPORT_STEPS:
        record = state.steps.get(key)
        if record is not None and record.need_regen:
            return key
    return None


def current_passport_step(state: CharacterState) -> str:
    """Which frame the passport screen should show.

    Honours the ``need_regen`` gate first (jump to the earliest flagged frame),
    then the persisted ``current_step`` when it is a passport frame, else the
    first frame. Always returns a valid passport step_key.
    """
    pending = first_pending_passport(state)
    if pending is not None:
        return pending
    current = state.current_step
    if current is not None and current in PASSPORT_STEPS:
        return current
    return PASSPORT_STEPS[0]


def next_passport_step(step_key: str) -> str | None:
    """Next frame after ``step_key``, or ``None`` if it is the last frame."""
    idx = passport_index(step_key)
    nxt = idx + 1
    return PASSPORT_STEPS[nxt] if nxt < len(PASSPORT_STEPS) else None


def previous_passport_step(step_key: str) -> str | None:
    """Previous frame before ``step_key``, or ``None`` if it is the first frame."""
    idx = passport_index(step_key)
    return PASSPORT_STEPS[idx - 1] if idx >= 1 else None


def passport_refs(state: CharacterState, step_key: str) -> list[Ref]:
    """Role references to attach when generating ``step_key`` (§3.5 / §4).

    Schedule: frame 1 attaches none (no approved refs yet — STYLE rides the
    frozen text layer); frame 2 attaches the face reference; frames 3-5 attach
    face + body. A reference is included only when its source frame is approved
    and the file is present on disk (defensive against a mid-regeneration ref).
    """
    idx = passport_index(step_key)
    wanted: list[tuple[str, RefRole]] = []
    if idx >= 1:
        wanted.append(("passport_face", "face"))
    if idx >= 2:
        wanted.append(("passport_body", "body"))
    refs: list[Ref] = []
    for src_key, role in wanted:
        record = state.steps.get(src_key)
        if record is None or not record.approved_path:
            continue
        path = character_asset(state.character_id, record.approved_path)
        if path.is_file():
            refs.append(Ref(path=str(path), role=role))
    return refs


def apply_layer_edit(
    state: CharacterState,
    step_key: str,
    *,
    face: str | None = None,
    body: str | None = None,
    outfit: str | None = None,
) -> None:
    """Persist edited layer text onto the character — only for editable layers.

    Writing only the frame's editable layers means a frozen FACE/BODY/OUTFIT can
    never be clobbered by a stray value coming back from the (read-only) widget.
    """
    editable = editable_layers(step_key)
    if face is not None and "face" in editable:
        state.prompt_layers.face = face.strip()
    if body is not None and "body" in editable:
        state.prompt_layers.body = body.strip()
    # OUTFIT is editable on frames 1-2 only until the base outfit is frozen
    # (after frame-2 approval it is read-only everywhere, §1/§4) — never clobber it.
    if outfit is not None and "outfit" in editable and not state.base_outfit.frozen:
        state.base_outfit.prompt = outfit.strip()


def _flag_downstream_stale(state: CharacterState, step_key: str) -> None:
    """Mark later already-approved frames stale after a ref frame was regenerated."""
    start = passport_index(step_key) + 1
    for later_key in PASSPORT_STEPS[start:]:
        record = state.steps.get(later_key)
        if record is not None and record.approved_path:
            record.stale = True


def generate_passport_frame(
    state: CharacterState,
    step_key: str,
    *,
    regenerate: bool,
    meter: CostLedger | None = None,
    model: str | None = None,
) -> GenerationResult:
    """Generate (or regenerate) one passport frame; never raises on API failure.

    The new image is written to a pending file first, so a failed call leaves
    the previous frame untouched (the user keeps their last good shot and the
    preserved prompt). On success the previous frame — if any — is archived to
    ``rejected/`` (never overwritten, §5) and the new one moves into
    ``refs/<step_key>.png``. A fresh generation is always left UN-approved
    (``approved_path`` cleared): the user must press «Утвердить».

    Regenerating clears the frame's ``need_regen`` gate and its own ``stale``
    flag; regenerating an identity-reference frame (FACE/BODY) flags later
    approved frames stale so the UI can warn about cascade drift.
    """
    _require_passport(step_key)
    char_dir = character_dir(state.character_id)
    relative = f"{REFS_DIR}/{step_key}.png"
    out = char_dir / REFS_DIR / f"{step_key}.png"
    pending = out.with_name(f"{out.name}.pending")

    record = state.steps.setdefault(step_key, StepRecord())
    if regenerate:
        # §5: «Перегенерить» clears the AI-edit gate and this frame's own warning.
        record.need_regen = False
        record.stale = False

    layers = build_prompt_layers(state, step_key, overrides=build_step_overrides(state, step_key))
    refs = passport_refs(state, step_key)
    result = generate_image(
        layers,
        refs,
        outfit_conflict=False,  # passport OUTFIT == base outfit == refs' outfit (§3.5)
        output_path=pending,
        model=model,
        meter=meter,
    )
    if not result.ok:
        pending.unlink(missing_ok=True)
        return result

    if out.exists():
        archive_to_rejected(char_dir, step_key, out)
    pending.replace(out)
    record.last_path = relative
    record.approved_path = None  # a new shot must be (re)approved
    record.prompt_layers = to_prompt_layers(layers)
    if step_key == "passport_body":
        # A fresh (unapproved) body shot un-freezes the base outfit it carried —
        # mirror of approve_passport_frame; it re-freezes on the next approval.
        state.base_outfit.frozen = False
        state.base_outfit.ref = None
    if regenerate and is_ref_frame(step_key):
        _flag_downstream_stale(state, step_key)
    return GenerationResult(image_path=str(out), ok=True, error=None, usage=result.usage)


def approve_passport_frame(state: CharacterState, step_key: str) -> None:
    """Approve the current shot of ``step_key`` and apply the freeze rules (§1/§4).

    The last generated shot becomes the approved reference; ``need_regen`` and
    the cascade ``stale`` flag are cleared. Approving frame 2 freezes the base
    outfit and records the body shot as its reference. FACE/BODY "frozen"
    semantics are implied by the approved frame (the field is read-only on later
    frames); the only persisted freeze flag is ``base_outfit.frozen``.

    Raises ``ValueError`` if there is no generation to approve.
    """
    _require_passport(step_key)
    record = state.steps.get(step_key)
    if record is None or not record.last_path:
        msg = f"cannot approve {step_key!r}: no generation yet"
        raise ValueError(msg)
    record.approved_path = record.last_path
    record.need_regen = False
    record.stale = False
    if step_key == "passport_body":
        state.base_outfit.frozen = True
        state.base_outfit.ref = record.approved_path


def all_passport_approved(state: CharacterState) -> bool:
    """True once every one of the five passport frames has an approved shot."""
    return all(
        (record := state.steps.get(key)) is not None and bool(record.approved_path)
        for key in PASSPORT_STEPS
    )


def cascade_warning(state: CharacterState, step_key: str) -> str | None:
    """The cascade warning text for ``step_key`` if it is flagged stale, else ``None``."""
    record = state.steps.get(step_key)
    if record is not None and record.stale:
        return CASCADE_WARNING
    return None
