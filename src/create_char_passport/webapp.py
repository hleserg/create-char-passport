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

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from create_char_passport.screens.router import ScreenId, WizardSession, resume_screen
from create_char_passport.state import CharacterState, CostLedger
from create_char_passport.storage import list_character_ids, load_state
from create_char_passport.wizard.extraction import extract_characters

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

    web_root = web_dir or _REPO_WEB
    if web_root.is_dir():
        # Mounted last so the explicit ``/api`` routes above always win.
        app.mount("/", StaticFiles(directory=str(web_root), html=True), name="web")
    return app


app = create_app()
