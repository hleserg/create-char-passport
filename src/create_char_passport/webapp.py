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

import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from create_char_passport.screens.router import ScreenId, WizardSession, resume_screen
from create_char_passport.state import (
    BASE_EMOTION_STEP,
    PASSPORT_STEPS,
    CharacterState,
    CostLedger,
    emotion_step,
    normalize_character_table,
)
from create_char_passport.storage import (
    REFS_DIR,
    archive_to_rejected,
    character_asset,
    character_dir,
    list_character_ids,
    load_state,
    save_state,
)
from create_char_passport.wizard import (
    apply_table,
    character_from_extracted,
    set_base_emotion,
    set_emotions_enabled,
    set_outfits_enabled,
    set_props_enabled,
    sync_outfits,
    sync_props,
)
from create_char_passport.wizard.emotions import (
    generate_base_emotion,
    generate_emotion,
    missing_emotion_refs,
)
from create_char_passport.wizard.extraction import extract_characters
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
        "missing": missing_emotion_refs(state),
        "cost": _cost_payload(state.cost),
    }


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
    def frame_image(character_id: str, step_key: str) -> FileResponse:
        """Serve a character's generated frame ``refs/<step_key>.png``."""
        if not step_key.replace("_", "").isalnum():
            raise HTTPException(status_code=400, detail="bad step key")
        path = character_asset(character_id, f"{REFS_DIR}/{step_key}.png")
        if not path.is_file():
            raise HTTPException(status_code=404, detail="no image")
        return FileResponse(str(path))

    @app.get("/api/character/{character_id}/emotions")
    def emotions(character_id: str, request: Request, response: Response) -> dict[str, Any]:
        """Serialise the emotions phase (series + base emotion)."""
        sess = _get_session(request, response)
        state = _load_for_session(sess, character_id)
        if state is None:
            raise HTTPException(status_code=404, detail="character not found")
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

    web_root = web_dir or _REPO_WEB
    if web_root.is_dir():
        # Mounted last so the explicit ``/api`` routes above always win.
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="web")
    return app


app = create_app()
