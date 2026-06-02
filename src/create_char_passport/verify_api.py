"""Verify API — thin generation endpoints for routing paid calls through the Space.

The dev machine may sit in a region the Gemini API refuses ("User location is
not supported for the API use"); the deployed HF Space runs in a supported
region. These two functions are exposed as hidden Gradio API endpoints
(``api_name="verify_generate"`` / ``"verify_llm"``) so a local verify harness can
drive *real* generation through the Space via ``gradio_client``. The Space is
private, so Hugging Face token auth gates access — no extra secret needed.

Both wrap the canonical engine (K2): the same ``generate_image`` / ``call_llm``
the app uses, so there is no logic drift between local and routed generation.
"""

from __future__ import annotations

import base64
import json
import tempfile
from pathlib import Path

from create_char_passport.gen import Ref, call_llm, generate_image


def verify_generate_image(
    layers_json: str,
    ref_files: list[str] | None,
    roles_json: str,
    outfit_conflict: bool,
) -> str:
    """Run :func:`generate_image` from JSON-encoded layers + uploaded refs.

    ``ref_files`` are the uploaded reference image paths (Gradio fills them);
    ``roles_json`` is the matching list of role strings. Returns the generated
    image path (Gradio returns the file to the client). Raises on failure so the
    client sees the error rather than a silent empty result.
    """
    layers = json.loads(layers_json or "{}")
    roles = json.loads(roles_json or "[]")
    files = list(ref_files or [])
    refs = [Ref(path=str(f), role=role) for f, role in zip(files, roles, strict=False)]
    out = Path(tempfile.mkdtemp(prefix="verify_")) / "frame.png"
    result = generate_image(layers, refs, outfit_conflict=bool(outfit_conflict), output_path=out)
    if not result.ok:
        msg = result.error or "generation failed"
        raise RuntimeError(msg)
    return str(out)


def verify_call_llm(prompt: str, image_files: list[str] | None) -> str:
    """Run :func:`call_llm` with the given prompt + optional uploaded images."""
    files = list(image_files or [])
    images_b64 = [base64.b64encode(Path(f).read_bytes()).decode("ascii") for f in files]
    return call_llm(prompt or "", images_b64=images_b64 or None)
