"""Props phase — 1–3 product-shot frames per prop, no character (HLE-734, §5).

Each prop (and magic / effect — same mechanism) gets up to ``MAX_PROP_SHOTS``
product-shot frames. A shot is generated WITHOUT the character: STYLE layer +
the shot's own prompt, on a clean background, with the STYLE reference image as
the only role reference (no face/body/outfit/expression — the object stands on
its own, §5). ``generate_image`` rides through :func:`render_step_image` (patched
in tests via ``wizard.generation``).

The shot's prompt is injected into the COMPOSITION layer alongside the
PRODUCT_SHOT preset (props have no FACE/BODY/OUTFIT subject layer). Prompts and
the "what" description persist per shot even before any generation.
"""

from __future__ import annotations

from create_char_passport.gen import (
    GenerationResult,
    Ref,
    SceneId,
    build_prompt_layers,
    effective_composition,
)
from create_char_passport.state import (
    CharacterState,
    CostLedger,
    PropEntry,
    PropShot,
    prop_shot_step,
)
from create_char_passport.storage import character_asset
from create_char_passport.wizard.generation import render_step_image, style_ref

PRODUCT_SHOT_HINT: str = (
    "Product-shot предмета/эффекта на чистом фоне — БЕЗ персонажа, без рук, без рамок и надписей."
)

# At most this many product-shot frames per prop (§5: 1 by default, max 3).
MAX_PROP_SHOTS: int = 3


def _require_prop(state: CharacterState, index: int) -> PropEntry:
    """Return ``state.props[index]`` or raise ``IndexError`` for a bad index."""
    props = state.props
    if not 0 <= index < len(props):
        msg = f"prop index out of range: {index}"
        raise IndexError(msg)
    return props[index]


def generate_prop_shot(
    state: CharacterState,
    index: int,
    n: int,
    *,
    meter: CostLedger | None = None,
    model: str | None = None,
) -> GenerationResult:
    """Generate product-shot ``n`` (1-based) for prop ``index`` and store its ref.

    No character: only the STYLE reference image is attached; FACE/BODY/OUTFIT/
    EXPRESSION layers are blanked and the shot's own prompt is appended to the
    PRODUCT_SHOT COMPOSITION. Raises ``IndexError`` for a bad prop/shot index.
    """
    prop = _require_prop(state, index)
    if not 1 <= n <= len(prop.shots):
        msg = f"prop shot index out of range: {n}"
        raise IndexError(msg)
    refs: list[Ref] = []
    style = style_ref(state)
    if style is not None:
        refs.append(style)
    composition = effective_composition(state, SceneId.PRODUCT_SHOT)
    shot_text = prop.shots[n - 1].prompt.strip()
    if shot_text:
        composition = f"{composition}\n{shot_text}"
    layers = build_prompt_layers(
        state,
        prop_shot_step(prop.id, n),
        overrides={
            "face": "",
            "body": "",
            "outfit": "",
            "expression": "",
            "composition": composition,
        },
    )
    result, relative = render_step_image(
        state, prop_shot_step(prop.id, n), layers, refs, meter=meter, model=model
    )
    if result.ok:
        prop.shots[n - 1].ref = relative
    return result


def add_prop_shot(state: CharacterState, index: int) -> int:
    """Append an empty product-shot slot to prop ``index``; return its 1-based n.

    Capped at :data:`MAX_PROP_SHOTS`; at the cap this is a no-op returning the
    current count, so state never holds a shot with no UI cell.
    """
    prop = _require_prop(state, index)
    if len(prop.shots) < MAX_PROP_SHOTS:
        prop.shots.append(PropShot())
    return len(prop.shots)


def delete_prop_shot(state: CharacterState, index: int, n: int) -> None:
    """Remove product-shot ``n`` (1-based) from prop ``index`` (no-op if absent)."""
    prop = _require_prop(state, index)
    if 1 <= n <= len(prop.shots):
        del prop.shots[n - 1]


def shot_has_generation(state: CharacterState, index: int, n: int) -> bool:
    """True if shot ``n`` of prop ``index`` has a generated ref on disk."""
    prop = _require_prop(state, index)
    if not 1 <= n <= len(prop.shots):
        return False
    ref = prop.shots[n - 1].ref
    return bool(ref) and character_asset(state.character_id, ref).is_file()


def first_prop_step(state: CharacterState) -> str | None:
    """Step key of the first prop's first shot (the phase entry cursor), or ``None``."""
    return prop_shot_step(state.props[0].id, 1) if state.props else None


def current_prop_index(state: CharacterState) -> int | None:
    """Index of the prop the cursor (``current_step``) is on, or ``None``."""
    step = state.current_step
    if not step:
        return None
    for i, prop in enumerate(state.props):
        if step.startswith(f"prop_{prop.id}_shot_"):
            return i
    return None


def adjacent_prop_step(state: CharacterState, index: int, *, forward: bool) -> str | None:
    """Step key of the next/previous prop relative to ``index``, or ``None`` at the edge."""
    nxt = index + 1 if forward else index - 1
    return prop_shot_step(state.props[nxt].id, 1) if 0 <= nxt < len(state.props) else None
