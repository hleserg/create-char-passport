"""Generation engine — contract K2.

A single entry point per task:

* :func:`generate_image` → image bytes saved into ``refs/``.
* :func:`call_llm` → raw text response from the LLM.

Both swallow API errors into a typed result so the UI can show the retry
button without losing the user's prompt (DoD §7.4 in ``plan/proekt_zametki.md``).

The Gemini client is built lazily (``_get_client``) so tests can monkeypatch
the factory and run without a real API key.

# PLAYBOOK-START
# id: lazy-llm-client-for-testability
# title: Lazy client factory keeps API code unit-testable
# status: draft
# category: testing
# tags: [llm, testing, di]
# Don't construct external SDK clients at import time. A nullary factory
# (``_get_client``) is trivial to monkeypatch in tests, so error paths
# (429, timeout, malformed response) become reachable without network or
# real credentials — and module import stays side-effect-free.
# PLAYBOOK-END
"""

from __future__ import annotations

import base64
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from create_char_passport.config import get_settings
from create_char_passport.gen.pricing import (
    CallUsage,
    extract_usage,
    record_image,
    record_llm,
)
from create_char_passport.gen.prompt import LAYER_NAMES, render_prompt_text
from create_char_passport.state import CostLedger

logger = logging.getLogger(__name__)

LAYER_ORDER: tuple[str, ...] = LAYER_NAMES

RefRole = Literal["face", "body", "style", "outfit"]


@dataclass(slots=True)
class Ref:
    """A reference image tagged with the role the generator should give it."""

    path: str
    role: RefRole


@dataclass(slots=True)
class GenerationResult:
    """Outcome of one :func:`generate_image` call.

    ``ok`` is the bit the UI cares about: when ``False``, ``error`` carries
    a short user-friendly message and ``image_path`` is ``None`` (so we
    never write back a "step succeeded" flag for a failed call). ``usage``
    carries the response's token counts for transparency (cost is metered via
    the ``meter`` argument; see :mod:`create_char_passport.gen.pricing`).
    """

    image_path: str | None
    ok: bool
    error: str | None = None
    usage: CallUsage | None = None


_OUTFIT_CONFLICT_RULE = (
    "use the attached images ONLY for face identity and body build. "
    "IGNORE the clothing in the references — the character now wears the "
    "outfit described in the [OUTFIT] layer above."
)


def _get_client() -> Any:
    """Lazy Gemini client factory. Monkeypatched in tests."""
    from google import genai  # type: ignore[import-not-found]

    return genai.Client(api_key=get_settings().gemini_api_key)


# Per-role guidance spelled out in the text part so the generator knows exactly
# what to take from each attached image (and what to ignore) — §3.5.
_ROLE_GUIDANCE: dict[str, str] = {
    "style": (
        "the ART-STYLE reference — copy ONLY its artistic manner (medium, line work, "
        "shading, colour palette, rendering); take NOTHING of its content, characters, "
        "pose, objects or background"
    ),
    "face": "the FACE reference — copy this character's facial identity only",
    "body": (
        "the BODY reference — copy this character's build and proportions only, NOT the clothing"
    ),
    "outfit": "the OUTFIT reference — copy the clothing only",
}


def _role_caption(refs: list[Ref]) -> str:
    """Human-readable mapping of ``image N → role`` for the text part.

    Each line states what to take from that image and what to ignore, so the
    generator never lifts content from the style image or clothing from the body
    reference (§3.5). Unknown roles fall back to ``"<role> reference"``.
    """
    if not refs:
        return ""
    rows = [
        f"image {i + 1} = {_ROLE_GUIDANCE.get(r.role, f'{r.role} reference')}"
        for i, r in enumerate(refs)
    ]
    return "Reference images (do not invent new ones):\n" + "\n".join(rows)


def _build_text_part(
    prompt_layers: dict[str, str],
    refs: list[Ref],
    outfit_conflict: bool,
) -> str:
    """Compose the textual part the model sees alongside the inline images."""
    text = render_prompt_text(prompt_layers)
    caption = _role_caption(refs)
    pieces = [p for p in (text, caption) if p]
    if outfit_conflict:
        pieces.append(_OUTFIT_CONFLICT_RULE)
    return "\n\n".join(pieces)


def _encode_inline_image(path: str) -> dict[str, Any]:
    """Read a file into a ``{mime_type, data}`` inline-image dict."""
    file_path = Path(path)
    raw = file_path.read_bytes()
    mime, _ = mimetypes.guess_type(file_path.name)
    return {
        "mime_type": mime or "image/png",
        "data": base64.b64encode(raw).decode("ascii"),
    }


def _build_contents(
    prompt_layers: dict[str, str],
    refs: list[Ref],
    outfit_conflict: bool,
) -> list[Any]:
    """Pack inline-image parts + text into the Gemini ``contents`` payload."""
    parts: list[Any] = []
    for ref in refs:
        parts.append({"inline_data": _encode_inline_image(ref.path)})
    text = _build_text_part(prompt_layers, refs, outfit_conflict)
    if text:
        parts.append({"text": text})
    return parts


def _extract_image_bytes(response: Any) -> bytes | None:
    """Pull the first inline image out of a Gemini response."""
    candidates = getattr(response, "candidates", None) or []
    for cand in candidates:
        content = getattr(cand, "content", None)
        parts = getattr(content, "parts", None) or []
        for part in parts:
            inline = getattr(part, "inline_data", None)
            if inline is None:
                continue
            data = getattr(inline, "data", None)
            if isinstance(data, bytes):
                return data
            if isinstance(data, str):
                return base64.b64decode(data)
    return None


def _extract_text(response: Any) -> str:
    """Concatenate all text parts in a Gemini response."""
    text_attr = getattr(response, "text", None)
    if isinstance(text_attr, str) and text_attr:
        return text_attr
    out: list[str] = []
    for cand in getattr(response, "candidates", None) or []:
        for part in getattr(getattr(cand, "content", None), "parts", None) or []:
            t = getattr(part, "text", None)
            if isinstance(t, str) and t:
                out.append(t)
    return "\n".join(out)


def generate_image(
    prompt_layers: dict[str, str],
    refs: list[Ref],
    outfit_conflict: bool = False,
    *,
    output_path: str | Path,
    model: str | None = None,
    meter: CostLedger | None = None,
) -> GenerationResult:
    """Render one image — single entry point used by every generation step.

    ``output_path`` is where the resulting PNG bytes are written when the
    call succeeds. ``model`` overrides ``settings.image_model`` (useful for
    swapping to Nano Banana Pro when identity drifts on NB2). When a ``meter``
    is passed, a *successful* call's cost is added to it (a failed call is
    never billed).
    """
    try:
        from google.genai import types as genai_types  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - SDK is a hard dependency
        return GenerationResult(image_path=None, ok=False, error=f"SDK missing: {exc}")

    resolved_model = model or get_settings().image_model
    try:
        client = _get_client()
        config = genai_types.GenerateContentConfig(
            response_modalities=[genai_types.Modality.IMAGE, genai_types.Modality.TEXT],
        )
        response = client.models.generate_content(
            model=resolved_model,
            contents=_build_contents(prompt_layers, refs, outfit_conflict),
            config=config,
        )
    except Exception as exc:
        logger.warning("image generation failed: %s", exc.__class__.__name__)
        return GenerationResult(
            image_path=None,
            ok=False,
            error=_friendly_error(exc),
        )

    data = _extract_image_bytes(response)
    if data is None:
        return GenerationResult(
            image_path=None,
            ok=False,
            error="Generator returned no image — try again or refine the prompt.",
        )
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    if meter is not None:
        record_image(meter, resolved_model)
    return GenerationResult(image_path=str(out), ok=True, error=None, usage=extract_usage(response))


def call_llm(
    prompt: str,
    image_b64: str | None = None,
    *,
    images_b64: list[str] | None = None,
    model: str | None = None,
    meter: CostLedger | None = None,
) -> str:
    """LLM text call — used by extract-characters, style prompt, AI-check, AI-edit.

    ``image_b64`` attaches a single inline image; ``images_b64`` attaches a
    whole list (the style step sends ~5 reference photos in one multimodal
    call). Both may be combined — every image is sent ahead of the text part,
    in order: ``image_b64`` first, then ``images_b64``.

    Returns the raw LLM text on success, or an empty string on any API
    failure (the caller decides how to surface the retry). Errors are
    logged at WARNING level without the prompt body — never log raw user
    input (AGENTS.md hard rule). When a ``meter`` is passed, a *successful*
    call's token cost is added to it (a failed call is never billed).
    """
    parts: list[dict[str, Any]] = [{"text": prompt}]
    inline = list(images_b64 or [])
    if image_b64:
        inline.insert(0, image_b64)
    for data in reversed(inline):
        parts.insert(0, {"inline_data": {"mime_type": "image/png", "data": data}})

    resolved_model = model or get_settings().llm_model
    try:
        client = _get_client()
        response = client.models.generate_content(
            model=resolved_model,
            contents=parts,
        )
    except Exception as exc:
        logger.warning("llm call failed: %s", exc.__class__.__name__)
        return ""

    if meter is not None:
        record_llm(meter, resolved_model, extract_usage(response))
    return _extract_text(response)


def _friendly_error(exc: BaseException) -> str:
    """Map common API failure classes to a short user-facing message."""
    name = exc.__class__.__name__.lower()
    text = str(exc)
    if "429" in text or "rate" in name or "quota" in text.lower():
        return "Rate limit hit. Wait a moment and press Retry."
    if "timeout" in name or "timeout" in text.lower():
        return "Generator timed out. Press Retry — your prompt is preserved."
    return "Generation failed. Press Retry — your prompt is preserved."
