"""FastAPI backend for the redesigned web frontend (HLE-836, P2).

Serves the static design SPA from ``web/`` and exposes a small JSON API that
drives it over the *pure* core (``wizard`` / ``gen`` / ``ai`` / ``state`` /
``storage`` / ``screens.router``). The legacy Gradio app (``gradio_app``) stays
untouched; this module is its eventual replacement and the artefact P3 ships in
a Docker Space.

Design rules carried over from the Gradio layer:

* The pure core is the single source of truth — endpoints only orchestrate it.
* Cross-character calls (extraction) are billed to the *session* ledger only,
  never to an incidentally-loaded character (mirrors ``screens.handlers``).
* Blocking work (LLM / image generation) lives in plain ``def`` endpoints so
  FastAPI runs them in its threadpool and never wedges the event loop.

# PLAYBOOK-START
# id: rest-over-pure-core
# title: REST API as a thin shell over a UI-agnostic core
# status: draft
# category: architecture
# tags: [fastapi, layering, reuse]
# When a UI-coupled app (here: Gradio) has already factored its logic into a
# pure, framework-free core, a second UI (a REST + SPA frontend) becomes a thin
# shell: each endpoint orchestrates the same core and serialises its state. No
# domain logic is duplicated, so the core's own tests keep guarding behaviour
# and the two UIs cannot drift apart. Substitution test passes: true of any app
# with a clean domain layer under its presentation layer.
# PLAYBOOK-END
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import BaseModel, Field

from create_char_passport.ai.review import apply_step_prompt, check_step, edit_character
from create_char_passport.gen import SceneId
from create_char_passport.screens.router import ScreenId, WizardSession, resume_screen
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    PASSPORT_STEPS,
    CharacterState,
    CostLedger,
    OutfitEntry,
    PropEntry,
    PropShot,
    StepRecord,
    emotion_step,
    normalize_character_table,
    outfit_detail_step,
    outfit_step,
    prop_shot_step,
    state_to_dict,
)
from create_char_passport.storage import (
    REFS_DIR,
    REJECTED_DIR,
    archive_to_rejected,
    bucket_root,
    character_asset,
    character_dir,
    list_character_ids,
    load_state,
    save_state,
)
from create_char_passport.wizard import (
    apply_style,
    apply_table,
    character_from_extracted,
    compose_layers,
    draft_style_prompt,
    set_base_emotion,
    set_emotions_enabled,
    set_outfits_enabled,
    set_props_enabled,
    set_style_ref,
    sync_outfits,
    sync_props,
    translate_layer,
)
from create_char_passport.wizard.emotions import (
    generate_base_emotion,
    generate_emotion,
    missing_emotion_refs,
)
from create_char_passport.wizard.extraction import extract_characters
from create_char_passport.wizard.outfits import (
    add_outfit_detail,
    all_outfits_approved,
    approve_outfit,
    delete_outfit_detail,
    generate_outfit_detail,
    generate_outfit_scene,
    missing_outfit_scenes,
    outfit_scenes,
    required_scenes_present,
    set_outfit_complex,
    set_outfit_detail_prompt,
    set_outfit_prompt,
)
from create_char_passport.wizard.passport import (
    all_passport_approved,
    apply_layer_edit,
    approve_passport_frame,
    cascade_warning,
    current_passport_step,
    editable_layers,
    frame_criterion,
    frame_title,
    generate_passport_frame,
    passport_index,
)
from create_char_passport.wizard.props import (
    add_prop_shot,
    delete_prop_shot,
    generate_prop_shot,
    set_prop_shot_prompt,
)

# Repo-relative location of the SPA (``<repo>/web``); P3's Docker image overrides
# it via :func:`create_app`'s ``web_dir`` so the package and the static bundle can
# live anywhere in the container.
_REPO_WEB = Path(__file__).resolve().parents[2] / "web"
_SESSION_COOKIE = "cph_session"

# In-memory, transient per-session store: it holds only navigation, the running
# session cost, and the just-extracted draft list. The *character* is always
# persisted to the bucket (``storage``), so a Spaces restart loses nothing but
# the transient extraction draft — real work is resumed from the saved list.
_SESSIONS: dict[str, WizardSession] = {}

# ``screens.router`` screen -> SPA phase key (``PHASES`` in ``web/shared.jsx``).
# The dataset screen was dropped from the wizard (logic note #8) -> fold onto props.
_SCREEN_TO_PHASE: dict[ScreenId, str] = {
    ScreenId.HOME: "data",
    ScreenId.STYLE: "data",
    ScreenId.CHAR_DATA: "data",
    ScreenId.PASSPORT: "passport",
    ScreenId.EMOTIONS: "emotions",
    ScreenId.OUTFITS: "outfit",
    ScreenId.PROPS: "props",
    ScreenId.DATASET: "props",
    ScreenId.FINISH: "data",
}


class ExtractRequest(BaseModel):
    """Body of ``POST /api/extract`` — the pasted story text."""

    text: str = ""


class CreateRequest(BaseModel):
    """Body of ``POST /api/character`` — the picked extracted character's name."""

    name: str = ""


class TranslateRequest(BaseModel):
    """Body of ``POST /api/translate`` — Russian text + the target layer label."""

    text: str = ""
    layer: str = ""


class CheckRequest(BaseModel):
    """Body of ``POST /api/character/{id}/check`` — the step to review."""

    step_key: str


class StepPromptRequest(BaseModel):
    """Body of accept actions — write ``prompt`` into ``step_key``'s field."""

    step_key: str
    prompt: str = ""


class EditRequest(BaseModel):
    """Body of ``POST /api/character/{id}/edit`` — the free-form edit request."""

    request: str = ""


class AnketaRequest(BaseModel):
    """Body of ``PUT /api/character/{id}/anketa`` — the edited character-data form.

    ``card`` carries the seven trait fields, ``marks`` the особые приметы
    (stored as ``details``). ``emotions`` / ``outfits`` / ``props`` mirror the
    optional-block shapes the SPA renders.
    """

    card: dict[str, str] = Field(default_factory=dict)
    marks: str = ""
    emotions: dict[str, Any] = Field(default_factory=dict)
    outfits: dict[str, Any] = Field(default_factory=dict)
    props: dict[str, Any] = Field(default_factory=dict)


class ComposeRequest(BaseModel):
    """Body of ``POST /api/character/{id}/compose`` — optional current card edits."""

    card: dict[str, str] = Field(default_factory=dict)
    marks: str = ""


class PassportGenRequest(BaseModel):
    """Body of ``POST /api/character/{id}/passport/generate``."""

    step_key: str
    face: str | None = None
    body: str | None = None
    outfit: str | None = None
    regenerate: bool = False


class StepRequest(BaseModel):
    """Body of step actions that only need a ``step_key`` (e.g. approve)."""

    step_key: str


class EmotionRequest(BaseModel):
    """Body of emotion actions that target one series item by index."""

    index: int


class BaseEmotionRequest(BaseModel):
    """Body of ``POST /api/character/{id}/emotions/base`` (optional new value)."""

    value: str | None = None


class EnableRequest(BaseModel):
    """Body of a simple on/off toggle."""

    enabled: bool = True


class OutfitSceneRequest(BaseModel):
    """Body of ``POST /api/character/{id}/outfits/generate`` (one full-length scene)."""

    index: int
    scene: str
    prompt: str | None = None
    complex: bool | None = None


class OutfitRequest(BaseModel):
    """Body of outfit actions targeting one outfit by index (approve / add detail)."""

    index: int


class OutfitComplexRequest(BaseModel):
    """Body of ``POST /api/character/{id}/outfits/complex``."""

    index: int
    complex: bool


class OutfitDetailRequest(BaseModel):
    """Body of costume-detail actions (generate / delete) by outfit index + 1-based n."""

    index: int
    n: int
    prompt: str | None = None


_OUTFIT_SCENES: dict[str, SceneId] = {
    "front_full": SceneId.FRONT_FULL,
    "back_full": SceneId.BACK_FULL,
    "profile_full": SceneId.PROFILE_FULL,
}


class PropRequest(BaseModel):
    """Body of prop actions targeting one prop by index (add shot)."""

    index: int


class PropShotRequest(BaseModel):
    """Body of prop-shot actions (generate / delete) + optional editable fields."""

    index: int
    n: int
    what: str | None = None
    prompt: str | None = None


class StylePromptRequest(BaseModel):
    """Body of ``PUT /api/style`` — the edited STYLE-layer prompt."""

    prompt: str = ""


def _cost_payload(ledger: CostLedger) -> dict[str, Any]:
    """Serialise a cost ledger for the SPA topbar."""
    return {
        "total_usd": round(ledger.total_usd, 4),
        "image_calls": ledger.image_calls,
        "llm_calls": ledger.llm_calls,
        "has_estimate": ledger.has_estimate,
    }


def _extracted_payload(
    index: int, name: str, table: dict[str, str], drafts: tuple[str, str, str]
) -> dict[str, Any]:
    """Serialise one extracted character draft into a start-screen card."""
    face, body, outfit = drafts
    return {
        "id": f"ex{index}",
        "name": name,
        "table": dict(table),
        "face": face,
        "body": body,
        "outfit": outfit,
    }


def _has_generation(state: CharacterState) -> bool:
    """True if any step already carries a generated or approved frame."""
    return any(record.last_path or record.approved_path for record in state.steps.values())


def _saved_status(state: CharacterState) -> str:
    """Human status for the saved-characters table (matches the design vocabulary).

    ``current_step`` empty means the pipeline was finished (``resume_screen``
    rule) — "готов" once anything was generated, else still "только анкета".
    A live ``current_step`` is mid-pipeline: "пайп не завершён" when there is a
    frame already, otherwise the wizard never left the anketa.
    """
    if _has_generation(state):
        return "готов" if not state.current_step else "пайп не завершён"
    return "только анкета"


def _saved_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise a saved character into one start-screen table row."""
    ready = _saved_status(state) == "готов"
    return {
        "id": state.character_id,
        "name": state.name or state.character_id,
        "status": _saved_status(state),
        "step": None if ready else _SCREEN_TO_PHASE.get(resume_screen(state), "data"),
    }


def _saved_characters() -> list[dict[str, Any]]:
    """All saved characters from the bucket, serialised for the start screen."""
    rows: list[dict[str, Any]] = []
    for character_id in list_character_ids():
        state = load_state(character_id)
        if state is not None:
            rows.append(_saved_payload(state))
    return rows


# Card fields shown on the anketa (the 8th table key, ``details``, is the
# free-form особые приметы edited separately as ``marks``).
_CARD_KEYS: tuple[str, ...] = ("gender", "age", "build", "hair", "eyes", "skin", "role")


def _character_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise a full character into the anketa shape the SPA renders."""
    table = normalize_character_table(state.character_table)
    return {
        "id": state.character_id,
        "name": state.name or state.character_id,
        "card": {key: table.get(key, "") for key in _CARD_KEYS},
        "marks": table.get("details", ""),
        "base_outfit": state.base_outfit.prompt,
        "emotions": {
            "enabled": state.emotions.enabled,
            "items": [{"value": item.value, "ref": item.ref} for item in state.emotions.items],
            "base": {
                "enabled": state.emotions.base_emotion.enabled,
                "value": state.emotions.base_emotion.value,
            },
        },
        "outfits": {
            "enabled": state.outfits_enabled,
            "list": [
                {"id": outfit.id, "name": outfit.prompt, "complex": outfit.complex}
                for outfit in state.outfits
            ],
        },
        "props": {
            "enabled": state.props_enabled,
            "list": [
                {"id": prop.id, "name": prop.name, "shots": len(prop.shots) or 1}
                for prop in state.props
            ],
        },
        "phase": _SCREEN_TO_PHASE.get(resume_screen(state), "data"),
        "cost": _cost_payload(state.cost),
    }


def _frame_payload(state: CharacterState, step_key: str) -> dict[str, Any]:
    """Serialise one passport frame for the passport screen.

    FACE/BODY come from the canonical editable layers; OUTFIT is the base outfit
    (entered/tuned on frames 1-2, read-only after). Freeze + visibility mirror
    the passport rules: FACE editable on frame 1, BODY on frame 2, both frozen
    after; the BODY field only appears from frame 2 on.
    """
    index = passport_index(step_key)
    record = state.steps.get(step_key)
    editable = editable_layers(step_key)
    return {
        "key": step_key,
        "index": index,
        "title": frame_title(step_key),
        "criterion": frame_criterion(step_key),
        "editable": sorted(editable),
        "face": state.prompt_layers.face,
        "body": state.prompt_layers.body,
        "outfit": state.base_outfit.prompt,
        "show_body": index >= 1,
        "face_frozen": index >= 1,
        "body_frozen": index >= 2,
        "outfit_frozen": index >= 2 or state.base_outfit.frozen,
        "has_image": bool(record and record.last_path),
        "approved": bool(record and record.approved_path),
        "stale": bool(record and record.stale),
        "need_regen": bool(record and record.need_regen),
        "warning": cascade_warning(state, step_key),
    }


def _passport_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise the whole passport phase for the SPA."""
    return {
        "current_step": current_passport_step(state),
        "frames": [_frame_payload(state, key) for key in PASSPORT_STEPS],
        "all_approved": all_passport_approved(state),
        "style": state.prompt_layers.style,
        "cost": _cost_payload(state.cost),
    }


def _emotions_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise the emotions phase (series items + base emotion + missing set)."""
    base = state.emotions.base_emotion
    return {
        "enabled": state.emotions.enabled,
        "items": [
            {
                "index": i,
                "value": item.value,
                "step_key": emotion_step(item.value),
                "has_image": bool(item.ref),
            }
            for i, item in enumerate(state.emotions.items)
        ],
        "base": {
            "enabled": base.enabled,
            "value": base.value,
            "step_key": BASE_EMOTION_STEP,
            "has_image": bool(base.ref),
        },
        # The neutral emotion is NOT generated separately — it's the passport
        # front portrait. Surfaced so the UI shows it as the first cell.
        "neutral": {
            "step_key": "passport_face",
            "has_image": bool(
                (rec := state.steps.get("passport_face")) is not None and rec.last_path
            ),
        },
        "missing": missing_emotion_refs(state),
        "cost": _cost_payload(state.cost),
    }


def _outfit_payload(index: int, outfit: Any) -> dict[str, Any]:
    """Serialise one outfit (scenes + costume details + completeness)."""
    refs = outfit.refs
    scenes = [
        {
            "scene": scene.value,
            "step_key": f"{outfit_step(outfit.id)}_{scene.value}",
            "has_image": bool(getattr(refs, scene.value)),
            "approved": bool(getattr(refs, f"{scene.value}_approved")),
        }
        for scene in outfit_scenes(outfit)
    ]
    details = [
        {
            "n": i + 1,
            "prompt": detail.prompt,
            "step_key": outfit_detail_step(outfit.id, i + 1),
            "has_image": bool(detail.ref),
        }
        for i, detail in enumerate(outfit.details)
    ]
    return {
        "index": index,
        "id": outfit.id,
        "name": outfit.prompt,
        "complex": outfit.complex,
        "scenes": scenes,
        "details": details,
        "required_present": required_scenes_present(outfit),
    }


def _outfits_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise the outfits phase (additional outfits + base + completeness)."""
    return {
        "enabled": state.outfits_enabled,
        "base_outfit": state.base_outfit.prompt,
        "outfits": [_outfit_payload(i, o) for i, o in enumerate(state.outfits)],
        "all_approved": all_outfits_approved(state),
        "missing": missing_outfit_scenes(state),
        "cost": _cost_payload(state.cost),
    }


def _require_outfit_index(state: CharacterState, index: int) -> None:
    """Guard: 400 unless ``index`` names an existing additional outfit."""
    if not 0 <= index < len(state.outfits):
        raise HTTPException(status_code=400, detail="outfit index out of range")


def _props_payload(state: CharacterState) -> dict[str, Any]:
    """Serialise the props phase (each prop + its 1-3 product shots)."""
    return {
        "enabled": state.props_enabled,
        "items": [
            {
                "index": i,
                "id": prop.id,
                "name": prop.name,
                "shots": [
                    {
                        "n": j + 1,
                        "what": shot.what,
                        "prompt": shot.prompt,
                        "step_key": prop_shot_step(prop.id, j + 1),
                        "has_image": bool(shot.ref),
                    }
                    for j, shot in enumerate(prop.shots)
                ],
            }
            for i, prop in enumerate(state.props)
        ],
        "cost": _cost_payload(state.cost),
    }


def _require_prop_index(state: CharacterState, index: int) -> None:
    """Guard: 400 unless ``index`` names an existing prop."""
    if not 0 <= index < len(state.props):
        raise HTTPException(status_code=400, detail="prop index out of range")


def _build_archive(state: CharacterState) -> Path:
    """Zip the character's golden set into a finish archive (#9).

    Contents: ``passport.json`` (full state — all prompt layers per step) +
    ``approved/`` (the current ``refs/`` golden frames) + ``rejected/`` (archived
    attempts). Returned as a temp file the caller streams then the OS reaps.
    """
    cdir = character_dir(state.character_id)
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)  # noqa: SIM115
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "passport.json",
            json.dumps(state_to_dict(state), ensure_ascii=False, indent=2),
        )
        for src, label in ((REFS_DIR, "approved"), (REJECTED_DIR, "rejected")):
            folder = cdir / src
            if folder.is_dir():
                for item in sorted(folder.glob("*")):
                    if item.is_file():
                        zf.write(item, f"{label}/{item.name}")
    return Path(tmp.name)


# Reads from the HF Storage Bucket (Xet FUSE) are slow (a full 775 KB image took
# ~12s on prod), so each bucket file is copied to a local cache the first time it
# is served and everything after — thumbnails *and* the lightbox original — comes
# from local disk. Cache key includes mtime+size, so a regenerated frame refreshes.
_IMG_CACHE = Path(tempfile.gettempdir()) / "cph_imgcache"
_CACHE_HEADERS = {"Cache-Control": "public, max-age=86400"}


def _local_image(path: Path) -> Path:
    """Local cached copy of a bucket image (copied once); the bucket path on error."""
    _IMG_CACHE.mkdir(parents=True, exist_ok=True)
    try:
        stat = path.stat()
        local = _IMG_CACHE / f"{path.stem}_{int(stat.st_mtime)}_{stat.st_size}{path.suffix}"
    except OSError:
        return path
    if not local.exists():
        try:
            shutil.copyfile(path, local)
        except OSError:
            return path
    return local


def _serve_image(path: Path, width: int | None) -> Response:
    """Serve an image (locally cached), optionally downscaled to ``width`` px.

    The stored refs/frames are full-size; review grids only need a few hundred px.
    With ``width`` we return a small cached JPEG; without it the (cached) original.
    A non-decodable file falls back to streaming the raw bytes.
    """
    local = _local_image(path)
    if width and 0 < width <= 2048:
        thumb = _IMG_CACHE / f"{local.stem}_{width}.jpg"
        if not thumb.exists():
            try:
                with Image.open(local) as im:
                    im = im.convert("RGB")
                    im.thumbnail((width, width))
                    im.save(thumb, format="JPEG", quality=82)
            except (OSError, ValueError):
                return FileResponse(str(local))
        return FileResponse(str(thumb), media_type="image/jpeg", headers=_CACHE_HEADERS)
    return FileResponse(str(local), headers=_CACHE_HEADERS)


def _load_for_session(sess: WizardSession, character_id: str) -> CharacterState | None:
    """Resolve a character: the in-memory session copy if it matches, else the bucket.

    The session copy may carry unsaved edits, so it wins; otherwise we fall back
    to the persisted state (resume / open-saved). Either way the resolved state
    becomes the session's active character.
    """
    if sess.character is not None and sess.character.character_id == character_id:
        return sess.character
    state = load_state(character_id)
    if state is not None:
        sess.character = state
    return state


# --------------------------------------------------------------------------- #
# Project-level STYLE store (shared across characters; persisted in the bucket).
# --------------------------------------------------------------------------- #
_STYLE_DIRNAME = "_style"
_MAX_STYLE_REFS = 5


def _style_dir() -> Path:
    """Bucket-rooted folder holding the project's style refs + ``style.json``."""
    folder = bucket_root() / _STYLE_DIRNAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _load_style_meta() -> dict[str, Any]:
    """Load ``{prompt, approved}`` for the project style (defaults when absent)."""
    path = _style_dir() / "style.json"
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {"prompt": "", "approved": False}
    return {"prompt": "", "approved": False}


def _save_style_meta(meta: dict[str, Any]) -> None:
    """Persist the project style meta."""
    (_style_dir() / "style.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _style_refs() -> list[Path]:
    """The stored style reference images, in order."""
    return sorted(_style_dir().glob("ref_*.png"))


def _any_generation_exists() -> bool:
    """True once any character has a generated frame — STYLE is then locked (§1)."""
    for character_id in list_character_ids():
        state = load_state(character_id)
        if state is not None and _has_generation(state):
            return True
    return False


def _style_payload() -> dict[str, Any]:
    """Serialise the project STYLE for the start screen."""
    meta = _load_style_meta()
    refs = _style_refs()
    return {
        "prompt": meta.get("prompt", ""),
        "approved": bool(meta.get("approved", False)),
        "ref_keys": [p.stem for p in refs],
        "ref_count": len(refs),
        # Once any character was generated, STYLE is frozen project-wide: the
        # prompt can only change via the explicit "Изменить стиль" reset (which
        # warns that existing characters must be redrawn).
        "locked": _any_generation_exists(),
    }


def _apply_project_style(state: CharacterState) -> None:
    """Stamp the persistent project STYLE (prompt + first ref image) onto a character."""
    prompt = _load_style_meta().get("prompt", "")
    if prompt:
        apply_style(state, prompt)
    refs = _style_refs()
    if refs:
        set_style_ref(state, str(refs[0]))


def _get_session(request: Request, response: Response) -> WizardSession:
    """Resolve the cookie-bound session, minting + setting the cookie if absent."""
    sid = request.cookies.get(_SESSION_COOKIE)
    if not sid or sid not in _SESSIONS:
        sid = secrets.token_urlsafe(16)
        _SESSIONS[sid] = WizardSession()
        response.set_cookie(
            _SESSION_COOKIE,
            sid,
            httponly=True,
            samesite="lax",
            max_age=60 * 60 * 24 * 7,
        )
    return _SESSIONS[sid]


def create_app(web_dir: Path | None = None) -> FastAPI:
    """Build the FastAPI app: JSON API under ``/api`` + the ``web/`` SPA at ``/``."""
    app = FastAPI(title="Паспорт героя", version="0.3.0")

    @app.get("/api/health")
    def health() -> dict[str, bool]:
        """Liveness probe — no session, no side effects."""
        return {"ok": True}

    @app.get("/api/session")
    def session(request: Request, response: Response) -> dict[str, Any]:
        """Establish the session cookie and return the start-screen bootstrap data."""
        sess = _get_session(request, response)
        return {
            "cost": _cost_payload(sess.cost),
            "saved_characters": _saved_characters(),
        }

    @app.post("/api/extract")
    def extract(body: ExtractRequest, request: Request, response: Response) -> dict[str, Any]:
        """Run the paid character extraction and return editable drafts."""
        sess = _get_session(request, response)
        meter = CostLedger()
        sess.extracted_characters = list(extract_characters(body.text or "", meter=meter))
        # Cross-character call -> bill the session ledger only (per screens.handlers).
        sess.cost.merge(meter)
        characters = [
            _extracted_payload(i, ec.name, ec.table, (ec.face, ec.body, ec.outfit))
            for i, ec in enumerate(sess.extracted_characters)
        ]
        return {"characters": characters, "cost": _cost_payload(sess.cost)}

    @app.post("/api/translate")
    def translate(body: TranslateRequest, request: Request, response: Response) -> dict[str, Any]:
        """RU -> EN layer prompt (+ other-layer spillover hints). Bills the session."""
        sess = _get_session(request, response)
        meter = CostLedger()
        result = translate_layer(body.text or "", body.layer or "", meter=meter)
        sess.cost.merge(meter)
        return {
            "text": result.text,
            "suggestions": result.suggestions,
            "cost": _cost_payload(sess.cost),
        }

    @app.post("/api/character")
    def create_character(
        body: CreateRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Create + persist a character from a picked extraction draft."""
        sess = _get_session(request, response)
        draft = next(
            (ec for ec in sess.extracted_characters if getattr(ec, "name", None) == body.name),
            None,
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="character draft not found")
        state = character_from_extracted(draft, style_prompt=sess.style_prompt)
        # Stamp the persistent project STYLE (prompt + ref image) onto the new
        # character so its generations carry the frozen project style (§1).
        _apply_project_style(state)
        sess.character = state
        save_state(state)
        return {"character": _character_payload(state)}

    @app.get("/api/character/{character_id}")
    def get_character(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Load a character (session copy or bucket) for resume / anketa render."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        return {"character": _character_payload(state)}

    @app.put("/api/character/{character_id}/anketa")
    def save_anketa(
        character_id: str, body: AnketaRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Persist the edited anketa (trait card, приметы, optional blocks)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        apply_table(state, {**body.card, "details": body.marks})
        base = body.emotions.get("base") or {}
        set_emotions_enabled(state, bool(body.emotions.get("enabled")))
        set_base_emotion(state, bool(base.get("enabled")), str(base.get("value") or ""))
        set_outfits_enabled(state, bool(body.outfits.get("enabled")))
        sync_outfits(
            state,
            [
                [o.get("name", ""), o.get("complex", False)]
                for o in (body.outfits.get("list") or [])
            ],
        )
        set_props_enabled(state, bool(body.props.get("enabled")))
        sync_props(state, [[p.get("name", "")] for p in (body.props.get("list") or [])])
        save_state(state)
        return {"character": _character_payload(state)}

    @app.post("/api/character/{character_id}/compose")
    def compose(
        character_id: str, body: ComposeRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """LLM-compose FACE/BODY/OUTFIT/base-emotion drafts from the trait table (#13).

        Applies the current card edits first, then seeds the editable layer drafts
        (never the frozen ones — FACE after passport-face approval, BODY after
        passport-body, OUTFIT after the base outfit is frozen). Bills the ledgers.
        """
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        if body.card:
            apply_table(state, {**body.card, "details": body.marks})
        meter = CostLedger()
        composed = compose_layers(state.character_table, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        face_frozen = bool((r := state.steps.get("passport_face")) and r.approved_path)
        body_frozen = bool((r := state.steps.get("passport_body")) and r.approved_path)
        if composed.face and not face_frozen:
            state.prompt_layers.face = composed.face
        if composed.body and not body_frozen:
            state.prompt_layers.body = composed.body
        if composed.outfit and not state.base_outfit.frozen:
            state.base_outfit.prompt = composed.outfit
        if composed.base_emotion:
            state.emotions.base_emotion.value = composed.base_emotion
            state.emotions.base_emotion.enabled = True
        save_state(state)
        return {
            "character": _character_payload(state),
            "layers": {
                "face": state.prompt_layers.face,
                "body": state.prompt_layers.body,
                "outfit": state.base_outfit.prompt,
                "base_emotion": state.emotions.base_emotion.value,
            },
        }

    @app.post("/api/character/{character_id}/check")
    def ai_check(
        character_id: str, body: CheckRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """«Проверить с ИИ» one step: returns a justification + an optional new prompt."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        record = state.steps.get(body.step_key)
        preview = None
        if record and record.last_path:
            path = character_asset(character_id, record.last_path)
            preview = str(path) if path.is_file() else None
        meter = CostLedger()
        try:
            outcome = check_step(state, body.step_key, preview, meter=meter)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="not a reviewable step") from exc
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {
            "justification": outcome.justification,
            "new_prompt": outcome.new_prompt,
            "step_key": outcome.step_key,
            "ok": outcome.ok,
        }

    @app.post("/api/character/{character_id}/check/accept")
    def ai_check_accept(
        character_id: str, body: StepPromptRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Apply a check's proposed prompt into the step's field."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        applied = apply_step_prompt(state, body.step_key, body.prompt)
        save_state(state)
        return {"applied": applied, "character": _character_payload(state)}

    @app.post("/api/character/{character_id}/edit")
    def ai_edit(
        character_id: str, body: EditRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """«Правка с ИИ» over the whole character: returns per-step proposed edits."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        meter = CostLedger()
        outcome = edit_character(state, body.request or "", meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {
            "blocks": [
                {
                    "step_key": b.step_key,
                    "justification": b.justification,
                    "new_prompt": b.new_prompt,
                }
                for b in outcome.blocks
            ],
            "note": outcome.note,
            "ok": outcome.ok,
        }

    @app.post("/api/character/{character_id}/edit/accept")
    def ai_edit_accept(
        character_id: str, body: StepPromptRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Apply one edit block: write the prompt + raise the step's need_regen gate."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        applied = apply_step_prompt(state, body.step_key, body.prompt)
        if applied:
            state.steps.setdefault(body.step_key, StepRecord()).need_regen = True
        save_state(state)
        return {"applied": applied, "character": _character_payload(state)}

    @app.get("/api/character/{character_id}/passport")
    def passport(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Serialise the passport phase (5 frames, freeze state, images)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        return {"passport": _passport_payload(state)}

    @app.post("/api/character/{character_id}/passport/generate")
    def passport_generate(
        character_id: str, body: PassportGenRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Edit the frame's layers, then (re)generate it. Bills the character + session."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        if body.step_key not in PASSPORT_STEPS:
            raise HTTPException(status_code=400, detail="not a passport step")
        apply_layer_edit(state, body.step_key, face=body.face, body=body.body, outfit=body.outfit)
        meter = CostLedger()
        result = generate_passport_frame(
            state, body.step_key, regenerate=body.regenerate, meter=meter
        )
        state.cost.merge(meter)
        sess.cost.merge(meter)
        state.current_step = body.step_key
        save_state(state)
        return {
            "ok": result.ok,
            "error": result.error,
            "passport": _passport_payload(state),
        }

    @app.post("/api/character/{character_id}/passport/approve")
    def passport_approve(
        character_id: str, body: StepRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Approve the frame's current shot (applies the freeze rules)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        try:
            approve_passport_frame(state, body.step_key)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        save_state(state)
        return {"passport": _passport_payload(state)}

    @app.get("/api/character/{character_id}/image/{step_key}")
    def frame_image(character_id: str, step_key: str, w: int | None = None) -> Response:
        """Serve a character's generated frame ``refs/<step_key>.png`` (``?w=`` thumbnail)."""
        if not step_key.replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail="bad step key")
        path = character_asset(character_id, f"{REFS_DIR}/{step_key}.png")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no image")
        return _serve_image(path, w)

    @app.get("/api/character/{character_id}/emotions")
    def emotions(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Serialise the emotions phase (series + base emotion)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        return {"emotions": _emotions_payload(state)}

    @app.post("/api/character/{character_id}/emotions/enable")
    def emotions_enable(
        character_id: str, body: EnableRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Toggle the emotion series on/off (off -> not required for completion)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        set_emotions_enabled(state, body.enabled)
        save_state(state)
        return {"emotions": _emotions_payload(state)}

    @app.post("/api/character/{character_id}/emotions/generate")
    def emotions_generate(
        character_id: str, body: EmotionRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Generate one emotion-series portrait (point-wise). Bills character + session."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        if not 0 <= body.index < len(state.emotions.items):
            raise HTTPException(status_code=400, detail="emotion index out of range")
        meter = CostLedger()
        result = generate_emotion(state, body.index, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {"ok": result.ok, "error": result.error, "emotions": _emotions_payload(state)}

    @app.post("/api/character/{character_id}/emotions/base")
    def emotions_base(
        character_id: str, body: BaseEmotionRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Generate the base-emotion portrait (optionally updating its value first)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        if body.value is not None:
            set_base_emotion(state, True, body.value)
        meter = CostLedger()
        result = generate_base_emotion(state, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {"ok": result.ok, "error": result.error, "emotions": _emotions_payload(state)}

    @app.post("/api/character/{character_id}/emotions/delete")
    def emotions_delete(
        character_id: str, body: EmotionRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Soft-delete one emotion's shot: archive it to rejected/ and clear the ref (#10)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        if not 0 <= body.index < len(state.emotions.items):
            raise HTTPException(status_code=400, detail="emotion index out of range")
        item = state.emotions.items[body.index]
        if item.ref:
            frame = character_asset(character_id, item.ref)
            archive_to_rejected(character_dir(character_id), emotion_step(item.value), frame)
            item.ref = None
        save_state(state)
        return {"emotions": _emotions_payload(state)}

    @app.get("/api/character/{character_id}/outfits")
    def outfits(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Serialise the outfits phase (additional outfits + scenes + details)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        return {"outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/add")
    def outfits_add(request: Request, response: Response, character_id: str) -> dict[str, Any]:
        """Append a new (empty) additional outfit so the user can build it here."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        state.outfits_enabled = True
        used = [int(o.id) for o in state.outfits if o.id.isdigit()]
        new_id = str(max(used, default=0) + 1)
        state.outfits.append(OutfitEntry(id=new_id))
        save_state(state)
        return {"outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/generate")
    def outfits_generate(
        character_id: str, body: OutfitSceneRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Generate one full-length outfit scene (front/back/profile). Bills the ledgers."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        scene = _OUTFIT_SCENES.get(body.scene)
        if scene is None:
            raise HTTPException(status_code=400, detail="unknown outfit scene")
        if body.complex is not None:
            set_outfit_complex(state, body.index, body.complex)
        if body.prompt is not None:
            set_outfit_prompt(state, outfit_step(state.outfits[body.index].id), body.prompt)
        meter = CostLedger()
        result = generate_outfit_scene(state, body.index, scene, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {"ok": result.ok, "error": result.error, "outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/complex")
    def outfits_complex(
        character_id: str, body: OutfitComplexRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Toggle an outfit's 'complex' flag (adds the profile scene + detail block)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        set_outfit_complex(state, body.index, body.complex)
        save_state(state)
        return {"outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/approve")
    def outfits_approve(
        character_id: str, body: OutfitRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Approve an outfit (requires front+back present) and make it active."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        if not approve_outfit(state, body.index):
            raise HTTPException(status_code=400, detail="outfit incomplete (need front + back)")
        save_state(state)
        return {"outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/detail/add")
    def outfit_detail_add(
        character_id: str, body: OutfitRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Append an empty costume-detail slot to an outfit (capped)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        add_outfit_detail(state, body.index)
        save_state(state)
        return {"outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/detail/generate")
    def outfit_detail_generate(
        character_id: str, body: OutfitDetailRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Generate a costume-detail macro shot (#7); optionally set its prompt first."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        outfit = state.outfits[body.index]
        if not 1 <= body.n <= len(outfit.details):
            raise HTTPException(status_code=400, detail="detail index out of range")
        if body.prompt is not None:
            set_outfit_detail_prompt(state, outfit_detail_step(outfit.id, body.n), body.prompt)
        meter = CostLedger()
        result = generate_outfit_detail(state, body.index, body.n, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {"ok": result.ok, "error": result.error, "outfits": _outfits_payload(state)}

    @app.post("/api/character/{character_id}/outfits/detail/delete")
    def outfit_detail_delete(
        character_id: str, body: OutfitDetailRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Delete a costume-detail slot from an outfit."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_outfit_index(state, body.index)
        delete_outfit_detail(state, body.index, body.n)
        save_state(state)
        return {"outfits": _outfits_payload(state)}

    @app.get("/api/character/{character_id}/props")
    def props(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Serialise the props phase (each prop + its product shots)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        return {"props": _props_payload(state)}

    @app.post("/api/character/{character_id}/props/enable")
    def props_enable(
        character_id: str, body: EnableRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Toggle the props block on/off (props are optional; off -> nothing required)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        set_props_enabled(state, body.enabled)
        save_state(state)
        return {"props": _props_payload(state)}

    @app.post("/api/character/{character_id}/props/add")
    def props_add(request: Request, response: Response, character_id: str) -> dict[str, Any]:
        """Append a new (empty, 1-shot) prop so the user can build it here."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        state.props_enabled = True
        used = [int(p.id) for p in state.props if p.id.isdigit()]
        new_id = str(max(used, default=0) + 1)
        state.props.append(PropEntry(id=new_id, shots=[PropShot()]))
        save_state(state)
        return {"props": _props_payload(state)}

    @app.post("/api/character/{character_id}/props/shot/add")
    def prop_shot_add(
        character_id: str, body: PropRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Append an empty product-shot slot to a prop (capped at 3)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_prop_index(state, body.index)
        add_prop_shot(state, body.index)
        save_state(state)
        return {"props": _props_payload(state)}

    @app.post("/api/character/{character_id}/props/shot/generate")
    def prop_shot_generate(
        character_id: str, body: PropShotRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Generate one product shot (no character); optionally set what/prompt first."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_prop_index(state, body.index)
        prop = state.props[body.index]
        if not 1 <= body.n <= len(prop.shots):
            raise HTTPException(status_code=400, detail="shot index out of range")
        if body.what is not None:
            prop.shots[body.n - 1].what = body.what.strip()
        if body.prompt is not None:
            set_prop_shot_prompt(state, prop_shot_step(prop.id, body.n), body.prompt)
        meter = CostLedger()
        result = generate_prop_shot(state, body.index, body.n, meter=meter)
        state.cost.merge(meter)
        sess.cost.merge(meter)
        save_state(state)
        return {"ok": result.ok, "error": result.error, "props": _props_payload(state)}

    @app.post("/api/character/{character_id}/props/shot/delete")
    def prop_shot_delete(
        character_id: str, body: PropShotRequest, request: Request, response: Response
    ) -> dict[str, Any]:
        """Delete one product-shot slot from a prop."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        _require_prop_index(state, body.index)
        delete_prop_shot(state, body.index, body.n)
        save_state(state)
        return {"props": _props_payload(state)}

    @app.post("/api/character/{character_id}/finish")
    def finish(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Mark the character complete (clears the wizard cursor -> 'готов')."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        state.current_step = None
        save_state(state)
        return {"ok": True, "character": _saved_payload(state)}

    @app.get("/api/character/{character_id}/archive")
    def archive(character_id: str, request: Request, response: Response) -> FileResponse:
        """Download the finish ZIP — passport.json + approved/ + rejected/ (#9)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
        zip_path = _build_archive(state)
        filename = f"{state.character_id}_passport.zip"
        return FileResponse(str(zip_path), media_type="application/zip", filename=filename)

    @app.get("/api/style")
    def get_style(request: Request, response: Response) -> dict[str, Any]:
        """The project STYLE (prompt, refs, lock state)."""
        _get_session(request, response)
        return {"style": _style_payload()}

    @app.post("/api/style/refs")
    def style_refs(
        request: Request,
        response: Response,
        files: list[UploadFile] = File(default=[]),  # noqa: B008
    ) -> dict[str, Any]:
        """Append reference images (multipart); the 5th triggers the LLM draft.

        Multipart upload — NOT base64-in-JSON — because the Space proxy drops
        large JSON request bodies (see memory hf-space-bucket-and-body-limit).
        An empty upload still drafts if 5 refs are already present in the bucket.
        """
        sess = _get_session(request, response)
        folder = _style_dir()
        count = len(_style_refs())
        for upload in files:
            if count >= _MAX_STYLE_REFS:
                break
            raw = upload.file.read()
            if not raw:
                continue
            count += 1
            (folder / f"ref_{count}.png").write_bytes(raw)
        meta = _load_style_meta()
        drafted = False
        refs = _style_refs()
        if len(refs) >= _MAX_STYLE_REFS and not meta.get("prompt"):
            meter = CostLedger()
            prompt = draft_style_prompt([str(p) for p in refs], meter=meter)
            sess.cost.merge(meter)
            if prompt:
                meta = {"prompt": prompt, "approved": True}
                _save_style_meta(meta)
                drafted = True
        return {"style": _style_payload(), "drafted": drafted}

    @app.put("/api/style")
    def put_style(body: StylePromptRequest, request: Request, response: Response) -> dict[str, Any]:
        """Edit the STYLE prompt in place — allowed only before the first generation."""
        _get_session(request, response)
        if _any_generation_exists():
            raise HTTPException(
                status_code=409, detail="style is locked — use «Изменить стиль» to reset"
            )
        text = body.prompt.strip()
        _save_style_meta({"prompt": text, "approved": bool(text)})
        return {"style": _style_payload()}

    @app.post("/api/style/reset")
    def reset_style(request: Request, response: Response) -> dict[str, Any]:
        """«Изменить стиль»: clear the project style + refs so the user re-uploads."""
        _get_session(request, response)
        for ref in _style_refs():
            ref.unlink(missing_ok=True)
        _save_style_meta({"prompt": "", "approved": False})
        return {"style": _style_payload()}

    @app.get("/api/style/ref/{key}")
    def style_ref_image(key: str, w: int | None = None) -> Response:
        """Serve a stored style reference image (``ref_<n>``; ``?w=`` thumbnail)."""
        if not key.replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail="bad key")
        path = _style_dir() / f"{key}.png"
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no image")
        return _serve_image(path, w)

    web_root = web_dir or _web_dir_from_env() or _REPO_WEB
    if web_root.is_dir():
        # Mounted last so the explicit ``/api`` routes above always win.
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="web")
    return app


def _web_dir_from_env() -> Path | None:
    """SPA dir from ``CPH_WEB_DIR`` (set in the Docker image where the package is
    installed and ``web/`` is copied to a fixed path), or ``None`` to fall back."""
    value = os.environ.get("CPH_WEB_DIR")
    return Path(value) if value else None


app = create_app()
