"""Style step — the optional second AI input step (§4 "промт стиля").

If ``[STYLE]`` is not approved yet, the user uploads ~5 reference photos; one
multimodal LLM call drafts a single STYLE-layer prompt describing the shared
artistic manner; the user edits and approves it, freezing STYLE at the
session/project level. Approved style is then stamped onto every character's
``prompt_layers.style`` (§1 — STYLE is frozen from the start and never touched
again).

Drafting rides the K2 engine (``call_llm`` with ``images_b64``); the rest is
pure.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

from create_char_passport.gen import call_llm
from create_char_passport.state import CharacterState, CostLedger
from create_char_passport.storage import REFS_DIR, character_dir

STYLE_PROMPT: str = """\
You are writing the STYLE layer of a prompt for a consistent character-reference
pipeline. You are given several reference images that share one artistic manner.

Describe ONLY the shared visual style / medium / rendering — the manner an artist
would keep constant across every drawing: medium and technique (e.g. inked comic,
painted illustration), line work, shading, colour palette and saturation, level
of detail, overall mood of the rendering.

Do NOT describe any specific character, their anatomy, clothing, pose, expression,
background, or scene — those belong to other layers. Write one compact English
paragraph, no markdown, no preamble, just the style description itself.
"""


def _encode_image(path: str | Path) -> str:
    """Read an image file into base64 ASCII (PNG/JPEG bytes, as uploaded)."""
    return base64.b64encode(Path(path).read_bytes()).decode("ascii")


def draft_style_prompt(
    image_paths: list[str], *, model: str | None = None, meter: CostLedger | None = None
) -> str:
    """Draft a STYLE-layer prompt from reference photos via one multimodal call.

    Empty input short-circuits (no call). On any API failure ``call_llm``
    returns ``""`` and the caller keeps the field editable for a retry.
    ``meter`` is forwarded so the call's cost is attributed by the caller.
    """
    paths = [p for p in image_paths if p]
    if not paths:
        return ""
    images_b64 = [_encode_image(p) for p in paths]
    return call_llm(STYLE_PROMPT, images_b64=images_b64, model=model, meter=meter).strip()


def apply_style(state: CharacterState, style_prompt: str) -> None:
    """Stamp the approved STYLE prompt onto a character's frozen STYLE layer."""
    state.prompt_layers.style = style_prompt.strip()


def set_style_ref(state: CharacterState, src_image: str | Path | None) -> str | None:
    """Copy a chosen style image into the character bucket and record it.

    Stores it at ``refs/style.png`` and sets ``state.style_ref`` to that relative
    path, so the generator can attach it with role ``style`` on every frame (the
    *image* companion to the frozen ``prompt_layers.style`` text — plan §3.5 / §4
    step 1, where the style reference is the only image on the first frame).

    Returns the stored relative path, or ``None`` when ``src_image`` is missing /
    empty / not a file (the text STYLE layer still applies — the image is a bonus).
    """
    if not src_image:
        return None
    src = Path(src_image)
    if not src.is_file():
        return None
    destination = character_dir(state.character_id) / REFS_DIR / "style.png"
    shutil.copyfile(src, destination)
    state.style_ref = f"{REFS_DIR}/style.png"
    return state.style_ref
