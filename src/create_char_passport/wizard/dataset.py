"""Dataset phase — walk the composition array, auto-generate, hand-curate (HLE-730, §5).

The final phase. For each saved composition the wizard auto-generates one frame
(COMPOSITION = the composition prompt on a fixed neutral-grey studio background;
active OUTFIT via ``active_outfit_id``; EXPRESSION = base emotion or neutral via
K3; identity refs style+face+body). The user regenerates (the previous frame is
archived to ``rejected/`` — never deleted) and approves (the frame is copied into
the ``approved/`` archive, named by composition). When every composition is
approved the wizard finishes: ``current_step`` → ``None`` and the archive screen
shows samples.

Random backgrounds are deliberately NOT done (per the issue): the dataset is
shot on a plain neutral-grey background under studio light; the composition
prompt itself is the only per-frame variation and is fully editable.

``generate_image`` rides through :func:`render_step_image` (patched in tests via
``wizard.generation``). Working frames live at ``refs/<slug>.png``; approvals are
copied to ``approved/<slug>.png``; regenerations archive to
``rejected/<slug>_attempt<N>.png`` — all named by composition (§5).
"""

from __future__ import annotations

from create_char_passport.gen import GenerationResult, build_prompt_layers
from create_char_passport.gen.prompt import to_prompt_layers
from create_char_passport.state import (
    CharacterState,
    CostLedger,
    StepRecord,
    dataset_step,
    slugify,
)
from create_char_passport.storage import character_asset, save_to_approved
from create_char_passport.wizard.generation import identity_refs, render_step_image

# Editable/appendable starter compositions (§8: prompts not fixed — this is a
# seed the user extends). Each describes a pose/framing; the neutral-grey studio
# background is appended at render time, so these stay background-free.
DEFAULT_DATASET_COMPOSITIONS: tuple[str, ...] = (
    "full body, walking pose, mid-stride, seen from the front",
    "full body, sitting on a simple stool, relaxed",
    "full body, dynamic action pose, three-quarter view",
    "head and shoulders, head tilted slightly down",
    "full body, low-angle view from below",
    "full body, high-angle view from above",
)

# The fixed studio framing appended to every dataset COMPOSITION (no random
# background — neutral grey, studio light). Carries framing only (no expression).
BACKGROUND_DIRECTIVE: str = (
    "plain neutral grey background, soft even studio lighting, the character "
    "clearly framed, no text, no panel border, no frame, no lettering"
)


def ensure_compositions(state: CharacterState) -> None:
    """Seed the editable composition list with the starters if it is empty."""
    if not state.dataset_compositions:
        state.dataset_compositions = list(DEFAULT_DATASET_COMPOSITIONS)


def composition_values(state: CharacterState) -> list[str]:
    """The dataset composition prompts, in order."""
    return list(state.dataset_compositions)


def dataset_name(state: CharacterState, idx: int) -> str:
    """Composition slug for frame ``idx`` (the human-readable ``approved/`` name)."""
    text = state.dataset_compositions[idx] if 0 <= idx < len(state.dataset_compositions) else ""
    return slugify(text) if text.strip() else f"dataset_{idx}"


def approved_name(state: CharacterState, idx: int) -> str:
    """Unique ``approved/`` filename for frame ``idx`` — its slug, disambiguated.

    When two compositions slugify to the same value (e.g. duplicates), the index
    is appended so they never collide on one ``approved/*.png`` (else one frame
    would silently overwrite the other). Working/rejected files use the stable
    ``dataset_<idx>`` key (see :func:`generate_dataset_frame`), not the slug.
    """
    slug = dataset_name(state, idx)
    twins = sum(1 for j in range(len(state.dataset_compositions)) if dataset_name(state, j) == slug)
    return slug if twins <= 1 else f"{slug}_{idx}"


def _require_idx(state: CharacterState, idx: int) -> None:
    if not 0 <= idx < len(state.dataset_compositions):
        msg = f"dataset composition index out of range: {idx}"
        raise IndexError(msg)


def generate_dataset_frame(
    state: CharacterState,
    idx: int,
    *,
    meter: CostLedger | None = None,
    model: str | None = None,
) -> GenerationResult:
    """Generate the working frame for composition ``idx`` and store it.

    COMPOSITION = the composition prompt + the neutral-grey studio directive;
    OUTFIT follows ``active_outfit_id``; identity refs (style+face+body); the new
    outfit differs from the refs' clothing when a non-base outfit is active, so
    ``outfit_conflict`` is set accordingly. Regeneration archives the previous
    frame to ``rejected/<dataset_idx>_attempt<N>``.

    The working file is keyed by the stable ``dataset_<idx>`` (not the editable
    composition slug) so a prompt edit or a duplicate composition can never
    clobber another frame or skip the regen archive; the human-readable slug is
    used only for the ``approved/`` copy on approval.
    """
    _require_idx(state, idx)
    composition = f"{state.dataset_compositions[idx].strip()}\n{BACKGROUND_DIRECTIVE}".strip()
    layers = build_prompt_layers(state, dataset_step(idx), overrides={"composition": composition})
    result, relative = render_step_image(
        state,
        dataset_step(idx),
        layers,
        identity_refs(state),
        meter=meter,
        model=model,
        outfit_conflict=state.active_outfit_id != "base",
    )
    if result.ok and relative is not None:
        state.steps[dataset_step(idx)] = StepRecord(
            last_path=relative, prompt_layers=to_prompt_layers(layers)
        )
    return result


def approve_dataset_frame(state: CharacterState, idx: int) -> bool:
    """Copy the working frame for ``idx`` into ``approved/`` (named by composition).

    Returns ``False`` (no-op) when the frame has not been generated yet, else
    copies ``refs/dataset_<idx>.png`` → ``approved/<unique-slug>.png`` and records
    the approved path on the step. Idempotent: re-approving overwrites the same
    approved file.
    """
    _require_idx(state, idx)
    record = state.steps.get(dataset_step(idx))
    if record is None or not record.last_path:
        return False
    working = character_asset(state.character_id, record.last_path)
    if not working.is_file():
        return False
    char_dir = working.parent.parent  # <character>/refs/<file> → <character>
    destination = save_to_approved(char_dir, approved_name(state, idx), working)
    record.approved_path = f"{destination.parent.name}/{destination.name}"
    record.need_regen = False  # §Г: approving clears any AI-edit regen flag
    return True


def frame_generated(state: CharacterState, idx: int) -> bool:
    """True if composition ``idx`` has a working frame on disk."""
    record = state.steps.get(dataset_step(idx))
    if record is None or not record.last_path:
        return False
    return character_asset(state.character_id, record.last_path).is_file()


def frame_approved(state: CharacterState, idx: int) -> bool:
    """True if composition ``idx`` has been approved into the archive."""
    record = state.steps.get(dataset_step(idx))
    return record is not None and bool(record.approved_path)


def add_composition(state: CharacterState, text: str) -> int:
    """Append a new composition prompt; return its index. Blank text is ignored."""
    cleaned = text.strip()
    if cleaned:
        state.dataset_compositions.append(cleaned)
    return len(state.dataset_compositions) - 1


def edit_composition(state: CharacterState, idx: int, text: str) -> None:
    """Replace the prompt of composition ``idx`` (in-range only)."""
    if 0 <= idx < len(state.dataset_compositions):
        state.dataset_compositions[idx] = text.strip()


def all_dataset_approved(state: CharacterState) -> bool:
    """True when there is at least one composition and every one is approved."""
    if not state.dataset_compositions:
        return False
    return all(frame_approved(state, i) for i in range(len(state.dataset_compositions)))


def approved_samples(state: CharacterState) -> list[str]:
    """Absolute paths of the approved dataset frames that exist (for the archive)."""
    samples: list[str] = []
    for i in range(len(state.dataset_compositions)):
        record = state.steps.get(dataset_step(i))
        if record is not None and record.approved_path:
            path = character_asset(state.character_id, record.approved_path)
            if path.is_file():
                samples.append(str(path))
    return samples


def first_dataset_step(state: CharacterState) -> str | None:
    """Step key of the first composition (the phase entry cursor), or ``None``."""
    return dataset_step(0) if state.dataset_compositions else None


def current_dataset_index(state: CharacterState) -> int | None:
    """Index of the composition the cursor (``current_step``) is on, or ``None``."""
    step = state.current_step
    if not step:
        return None
    for i in range(len(state.dataset_compositions)):
        if step == dataset_step(i):
            return i
    return None


def adjacent_dataset_step(state: CharacterState, idx: int, *, forward: bool) -> str | None:
    """Step key of the next/previous composition relative to ``idx``, or ``None``."""
    nxt = idx + 1 if forward else idx - 1
    return dataset_step(nxt) if 0 <= nxt < len(state.dataset_compositions) else None
