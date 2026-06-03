"""Unit tests for the FastAPI backend (HLE-836, P2).

The LLM is never hit: ``extract_characters`` is monkeypatched at the
``webapp`` reference (mirrors ``test_handlers``), so every endpoint is covered
without a network or an API key.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from create_char_passport import webapp
from create_char_passport.config import get_settings
from create_char_passport.state import CharacterState, CostLedger, StepRecord, blank_state
from create_char_passport.storage import save_state
from create_char_passport.wizard import ExtractedCharacter


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the storage bucket at a throwaway dir for the duration of a test."""
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path
    get_settings.cache_clear()


@pytest.fixture
def client(bucket: Path) -> TestClient:
    """A TestClient over a fresh app whose SPA mount points at the real ``web/``."""
    return TestClient(webapp.create_app())


# --------------------------------------------------------------------------- #
# health + static mount
# --------------------------------------------------------------------------- #
def test_health(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"ok": True}


def test_serves_spa_index(client: TestClient) -> None:
    res = client.get("/")
    assert res.status_code == 200
    assert 'id="root"' in res.text


def test_missing_web_dir_skips_mount(bucket: Path, tmp_path: Path) -> None:
    app = webapp.create_app(web_dir=tmp_path / "does-not-exist")
    api = TestClient(app)
    assert api.get("/api/health").json() == {"ok": True}
    assert api.get("/").status_code == 404


# --------------------------------------------------------------------------- #
# session + cookie
# --------------------------------------------------------------------------- #
def test_session_sets_cookie_then_reuses_it(client: TestClient) -> None:
    first = client.get("/api/session")
    assert first.status_code == 200
    assert webapp._SESSION_COOKIE in first.cookies  # minted on the first call
    body = first.json()
    assert body["saved_characters"] == []
    assert body["cost"]["total_usd"] == 0.0
    # The TestClient keeps the cookie, so a second call resolves the same session.
    again = client.get("/api/session")
    assert again.status_code == 200


def test_session_lists_saved_characters(client: TestClient, bucket: Path) -> None:
    state = blank_state("Геро́н")
    state.current_step = "passport_face"
    state.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    save_state(state)
    rows = client.get("/api/session").json()["saved_characters"]
    assert len(rows) == 1
    assert rows[0]["name"] == "Геро́н"
    assert rows[0]["status"] == "пайп не завершён"
    assert rows[0]["step"] == "passport"


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #
def test_extract_returns_drafts_and_bills_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fake_extract(text: str, *, model: str | None = None, meter: CostLedger | None = None):
        assert text == "Герон вышел из таверны"
        if meter is not None:
            meter.llm_usd = 0.01
            meter.llm_calls = 1
        return [
            ExtractedCharacter(name="Герон", table={"gender": "male"}, face="broad nose"),
            ExtractedCharacter(name="Тайра"),
        ]

    monkeypatch.setattr(webapp, "extract_characters", fake_extract)
    body = client.post("/api/extract", json={"text": "Герон вышел из таверны"}).json()

    assert [c["name"] for c in body["characters"]] == ["Герон", "Тайра"]
    assert body["characters"][0]["table"] == {"gender": "male"}
    assert body["characters"][0]["face"] == "broad nose"
    assert body["characters"][0]["id"] == "ex0"
    assert body["cost"]["llm_calls"] == 1
    assert body["cost"]["total_usd"] == 0.01


def test_extract_empty_text_is_noop(client: TestClient) -> None:
    # No monkeypatch: real extract_characters short-circuits on blank text (no call).
    body = client.post("/api/extract", json={"text": "   "}).json()
    assert body["characters"] == []
    assert body["cost"]["llm_calls"] == 0


# --------------------------------------------------------------------------- #
# serialiser branches (status vocabulary)
# --------------------------------------------------------------------------- #
def _state_with(current_step: str | None, *, generated: bool) -> CharacterState:
    state = blank_state("X")
    state.current_step = current_step
    if generated:
        state.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    return state


def test_saved_status_vocabulary() -> None:
    assert webapp._saved_status(_state_with(None, generated=False)) == "только анкета"
    assert webapp._saved_status(_state_with(None, generated=True)) == "готов"
    assert webapp._saved_status(_state_with("passport_face", generated=True)) == "пайп не завершён"
    assert webapp._saved_status(_state_with("passport_face", generated=False)) == "только анкета"


def test_saved_payload_ready_has_no_step() -> None:
    payload = webapp._saved_payload(_state_with(None, generated=True))
    assert payload["status"] == "готов"
    assert payload["step"] is None


def test_saved_characters_skips_missing(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A listed id whose state.json vanished (race) must be skipped, not crash.
    monkeypatch.setattr(webapp, "list_character_ids", lambda: ["ghost"])
    assert webapp._saved_characters() == []


# --------------------------------------------------------------------------- #
# character: create / get / anketa round-trip
# --------------------------------------------------------------------------- #
def _seed_extracted(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Prime the client's session with one extracted draft (no network)."""

    def fake_extract(text: str, *, model: str | None = None, meter: CostLedger | None = None):
        return [
            ExtractedCharacter(
                name="Герон",
                table={"gender": "male", "age": "30"},
                face="broad nose",
                body="stocky",
            )
        ]

    monkeypatch.setattr(webapp, "extract_characters", fake_extract)
    client.post("/api/extract", json={"text": "history"})


def test_create_character_persists_and_serialises(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_extracted(client, monkeypatch)
    body = client.post("/api/character", json={"name": "Герон"}).json()["character"]
    assert body["id"] == "geron"
    assert body["card"]["gender"] == "male"
    assert body["phase"] == "data"
    assert client.get("/api/character/geron").status_code == 200  # persisted


def test_create_character_unknown_draft_404(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _seed_extracted(client, monkeypatch)
    assert client.post("/api/character", json={"name": "Nobody"}).status_code == 404


def test_get_character_not_found_404(client: TestClient) -> None:
    assert client.get("/api/character/ghost").status_code == 404


def test_get_character_from_bucket(client: TestClient, bucket: Path) -> None:
    state = blank_state("Тайра")
    state.character_table = {"gender": "female"}
    save_state(state)
    body = client.get("/api/character/tayra").json()["character"]
    assert body["name"] == "Тайра"
    assert body["card"]["gender"] == "female"


def test_save_anketa_round_trip(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_extracted(client, monkeypatch)
    client.post("/api/character", json={"name": "Герон"})
    res = client.put(
        "/api/character/geron/anketa",
        json={
            "card": {"gender": "male", "age": "35", "build": "athletic"},
            "marks": "scar on the left cheek",
            "emotions": {"enabled": True, "base": {"enabled": True, "value": "grim"}},
            "outfits": {"enabled": True, "list": [{"name": "plate armour", "complex": True}]},
            "props": {"enabled": True, "list": [{"name": "sword"}, {"name": ""}]},
        },
    )
    assert res.status_code == 200
    body = client.get("/api/character/geron").json()["character"]  # reload from bucket
    assert body["card"]["age"] == "35"
    assert body["marks"] == "scar on the left cheek"
    assert body["emotions"]["base"] == {"enabled": True, "value": "grim"}
    assert body["outfits"]["list"] == [{"id": "1", "name": "plate armour", "complex": True}]
    # the blank prop row is dropped; the kept one is born with one shot
    assert body["props"]["list"] == [{"id": "1", "name": "sword", "shots": 1}]


def test_save_anketa_not_found_404(client: TestClient) -> None:
    assert client.put("/api/character/ghost/anketa", json={"card": {}}).status_code == 404
