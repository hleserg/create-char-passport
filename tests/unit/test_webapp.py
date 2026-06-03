"""Unit tests for the FastAPI backend (HLE-836, P2).

The LLM is never hit: ``extract_characters`` is monkeypatched at the
``webapp`` reference (mirrors ``test_handlers``), so every endpoint is covered
without a network or an API key.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from create_char_passport import webapp
from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.state import (
    CharacterState,
    CostLedger,
    OutfitEntry,
    PropEntry,
    PropShot,
    StepRecord,
    blank_state,
)
from create_char_passport.storage import load_state, save_state
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


def test_web_dir_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CPH_WEB_DIR", raising=False)
    assert webapp._web_dir_from_env() is None
    monkeypatch.setenv("CPH_WEB_DIR", str(tmp_path))
    assert webapp._web_dir_from_env() == tmp_path


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


# --------------------------------------------------------------------------- #
# passport: serialize / generate / approve / image
# --------------------------------------------------------------------------- #
def _fake_gen_ok(layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_bytes(b"img-bytes")
    return GenerationResult(image_path=str(output_path), ok=True)


def _fake_gen_fail(layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    return GenerationResult(image_path=None, ok=False, error="boom")


def _make_character(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create the seeded 'Герон' and return its id."""
    _seed_extracted(client, monkeypatch)
    return client.post("/api/character", json={"name": "Герон"}).json()["character"]["id"]


def test_passport_serialise(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    pp = client.get(f"/api/character/{cid}/passport").json()["passport"]
    assert pp["current_step"] == "passport_face"
    assert [f["key"] for f in pp["frames"]] == list(webapp.PASSPORT_STEPS)
    assert pp["all_approved"] is False
    assert pp["frames"][0]["editable"] == ["face", "outfit"]
    assert pp["frames"][0]["show_body"] is False
    assert pp["frames"][1]["show_body"] is True


def test_passport_generate_then_approve(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    monkeypatch.setattr("create_char_passport.wizard.passport.generate_image", _fake_gen_ok)
    res = client.post(
        f"/api/character/{cid}/passport/generate",
        json={"step_key": "passport_face", "face": "broad nose", "outfit": "leather tunic"},
    ).json()
    assert res["ok"] is True
    assert res["passport"]["frames"][0]["has_image"] is True
    assert res["passport"]["frames"][0]["approved"] is False
    # the generated image is now served
    assert client.get(f"/api/character/{cid}/image/passport_face").status_code == 200
    # approve -> frozen
    pp = client.post(
        f"/api/character/{cid}/passport/approve", json={"step_key": "passport_face"}
    ).json()["passport"]
    assert pp["frames"][0]["approved"] is True


def test_passport_generate_failure_reports_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    monkeypatch.setattr("create_char_passport.wizard.passport.generate_image", _fake_gen_fail)
    res = client.post(
        f"/api/character/{cid}/passport/generate", json={"step_key": "passport_face"}
    ).json()
    assert res["ok"] is False
    assert res["error"] == "boom"
    assert res["passport"]["frames"][0]["has_image"] is False


def test_passport_generate_rejects_non_passport_step(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    res = client.post(f"/api/character/{cid}/passport/generate", json={"step_key": "emotion_x"})
    assert res.status_code == 400


def test_passport_approve_without_generation_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    res = client.post(f"/api/character/{cid}/passport/approve", json={"step_key": "passport_face"})
    assert res.status_code == 400


def test_passport_not_found_404(client: TestClient) -> None:
    assert client.get("/api/character/ghost/passport").status_code == 404


def test_frame_image_missing_and_bad_key(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    assert client.get(f"/api/character/{cid}/image/passport_face").status_code == 404
    assert client.get(f"/api/character/{cid}/image/bad-key").status_code == 400


# --------------------------------------------------------------------------- #
# emotions: serialize / generate / base / delete
# --------------------------------------------------------------------------- #
def _stub_emotion_gen(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("create_char_passport.wizard.generation.generate_image", _fake_gen_ok)


def test_emotions_serialise(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    emo = client.get(f"/api/character/{cid}/emotions").json()["emotions"]
    assert [i["value"] for i in emo["items"]] == ["angry, furious", "smiling warmly"]
    assert emo["items"][0]["step_key"] == "emotion_angry_furious"
    assert emo["base"]["enabled"] is False
    assert all(not i["has_image"] for i in emo["items"])


def test_emotions_generate_and_delete(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    _stub_emotion_gen(monkeypatch)
    res = client.post(f"/api/character/{cid}/emotions/generate", json={"index": 0}).json()
    assert res["ok"] is True
    assert res["emotions"]["items"][0]["has_image"] is True
    assert client.get(f"/api/character/{cid}/image/emotion_angry_furious").status_code == 200
    # soft-delete -> ref cleared, image archived to rejected/
    res = client.post(f"/api/character/{cid}/emotions/delete", json={"index": 0}).json()
    assert res["emotions"]["items"][0]["has_image"] is False


def test_emotions_base_generate(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    _stub_emotion_gen(monkeypatch)
    res = client.post(
        f"/api/character/{cid}/emotions/base", json={"value": "grim, brooding"}
    ).json()
    assert res["ok"] is True
    assert res["emotions"]["base"]["value"] == "grim, brooding"
    assert res["emotions"]["base"]["has_image"] is True


def test_emotions_generate_bad_index_400(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _make_character(client, monkeypatch)
    assert (
        client.post(f"/api/character/{cid}/emotions/generate", json={"index": 9}).status_code == 400
    )
    assert (
        client.post(f"/api/character/{cid}/emotions/delete", json={"index": 9}).status_code == 400
    )


def test_emotions_not_found_404(client: TestClient) -> None:
    assert client.get("/api/character/ghost/emotions").status_code == 404


def test_emotions_enable_toggle(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    off = client.post(f"/api/character/{cid}/emotions/enable", json={"enabled": False}).json()
    assert off["emotions"]["enabled"] is False
    on = client.post(f"/api/character/{cid}/emotions/enable", json={"enabled": True}).json()
    assert on["emotions"]["enabled"] is True


def test_emotions_payload_has_neutral(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    neutral = client.get(f"/api/character/{cid}/emotions").json()["emotions"]["neutral"]
    assert neutral["step_key"] == "passport_face"
    assert neutral["has_image"] is False


def test_outfits_add(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    cid = _make_character(client, monkeypatch)
    before = client.get(f"/api/character/{cid}/outfits").json()["outfits"]["outfits"]
    after = client.post(f"/api/character/{cid}/outfits/add").json()["outfits"]
    assert after["enabled"] is True
    assert len(after["outfits"]) == len(before) + 1


# --------------------------------------------------------------------------- #
# outfits: serialize / scene generate / complex / approve / details
# --------------------------------------------------------------------------- #
def _character_with_outfit(complex_: bool = False) -> str:
    state = blank_state("Аякс")
    state.prompt_layers.face = "scarred face"
    state.prompt_layers.body = "huge, muscular"
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="1", prompt="plate armour", complex=complex_)]
    save_state(state)
    return state.character_id


def test_outfits_serialise(client: TestClient, bucket: Path) -> None:
    cid = _character_with_outfit()
    out = client.get(f"/api/character/{cid}/outfits").json()["outfits"]
    assert out["enabled"] is True
    assert out["outfits"][0]["name"] == "plate armour"
    assert [s["scene"] for s in out["outfits"][0]["scenes"]] == ["front_full", "back_full"]
    assert out["outfits"][0]["required_present"] is False


def test_outfit_generate_scene_and_image(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _character_with_outfit()
    _stub_emotion_gen(monkeypatch)  # patches wizard.generation.generate_image
    res = client.post(
        f"/api/character/{cid}/outfits/generate",
        json={"index": 0, "scene": "front_full", "prompt": "gilded plate armour"},
    ).json()
    assert res["ok"] is True
    front = res["outfits"]["outfits"][0]["scenes"][0]
    assert front["has_image"] is True
    assert res["outfits"]["outfits"][0]["name"] == "gilded plate armour"
    assert client.get(f"/api/character/{cid}/image/{front['step_key']}").status_code == 200


def test_outfit_complex_adds_profile(client: TestClient, bucket: Path) -> None:
    cid = _character_with_outfit()
    res = client.post(
        f"/api/character/{cid}/outfits/complex", json={"index": 0, "complex": True}
    ).json()
    assert [s["scene"] for s in res["outfits"]["outfits"][0]["scenes"]] == [
        "front_full",
        "back_full",
        "profile_full",
    ]


def test_outfit_approve_requires_front_and_back(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _character_with_outfit()
    assert (
        client.post(f"/api/character/{cid}/outfits/approve", json={"index": 0}).status_code == 400
    )
    _stub_emotion_gen(monkeypatch)
    for scene in ("front_full", "back_full"):
        client.post(f"/api/character/{cid}/outfits/generate", json={"index": 0, "scene": scene})
    res = client.post(f"/api/character/{cid}/outfits/approve", json={"index": 0})
    assert res.status_code == 200
    assert res.json()["outfits"]["outfits"][0]["required_present"] is True


def test_outfit_detail_add_generate_delete(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _character_with_outfit(complex_=True)
    _stub_emotion_gen(monkeypatch)
    client.post(f"/api/character/{cid}/outfits/generate", json={"index": 0, "scene": "front_full"})
    add = client.post(f"/api/character/{cid}/outfits/detail/add", json={"index": 0}).json()
    assert len(add["outfits"]["outfits"][0]["details"]) == 1
    gen = client.post(
        f"/api/character/{cid}/outfits/detail/generate",
        json={"index": 0, "n": 1, "prompt": "engraved pauldron"},
    ).json()
    assert gen["ok"] is True
    assert gen["outfits"]["outfits"][0]["details"][0]["has_image"] is True
    rem = client.post(
        f"/api/character/{cid}/outfits/detail/delete", json={"index": 0, "n": 1}
    ).json()
    assert rem["outfits"]["outfits"][0]["details"] == []


def test_outfit_bad_index_and_scene_and_404(client: TestClient, bucket: Path) -> None:
    cid = _character_with_outfit()
    assert (
        client.post(
            f"/api/character/{cid}/outfits/generate", json={"index": 9, "scene": "front_full"}
        ).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/character/{cid}/outfits/generate", json={"index": 0, "scene": "sideways"}
        ).status_code
        == 400
    )
    assert client.get("/api/character/ghost/outfits").status_code == 404


# --------------------------------------------------------------------------- #
# props + finish + archive
# --------------------------------------------------------------------------- #
def _character_with_prop() -> str:
    state = blank_state("Молот")
    state.prompt_layers.style = "ink line"
    state.props_enabled = True
    state.props = [PropEntry(id="1", name="меч", shots=[PropShot()])]
    save_state(state)
    return state.character_id


def test_props_serialise(client: TestClient, bucket: Path) -> None:
    cid = _character_with_prop()
    pr = client.get(f"/api/character/{cid}/props").json()["props"]
    assert pr["enabled"] is True
    assert pr["items"][0]["name"] == "меч"
    assert pr["items"][0]["shots"][0]["step_key"] == "prop_1_shot_1"


def test_prop_shot_generate_add_delete(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = _character_with_prop()
    _stub_emotion_gen(monkeypatch)
    gen = client.post(
        f"/api/character/{cid}/props/shot/generate",
        json={"index": 0, "n": 1, "what": "общий вид", "prompt": "bronze sword, product shot"},
    ).json()
    assert gen["ok"] is True
    assert gen["props"]["items"][0]["shots"][0]["has_image"] is True
    assert client.get(f"/api/character/{cid}/image/prop_1_shot_1").status_code == 200
    added = client.post(f"/api/character/{cid}/props/shot/add", json={"index": 0}).json()
    assert len(added["props"]["items"][0]["shots"]) == 2
    rem = client.post(f"/api/character/{cid}/props/shot/delete", json={"index": 0, "n": 2}).json()
    assert len(rem["props"]["items"][0]["shots"]) == 1


def test_prop_bad_index_and_404(client: TestClient, bucket: Path) -> None:
    cid = _character_with_prop()
    assert client.post(f"/api/character/{cid}/props/shot/add", json={"index": 9}).status_code == 400
    assert client.get("/api/character/ghost/props").status_code == 404


def test_finish_marks_ready(client: TestClient, bucket: Path) -> None:
    cid = _character_with_prop()
    res = client.post(f"/api/character/{cid}/finish").json()
    assert res["ok"] is True
    # current_step cleared -> the saved-character row reads as "готов" once frames exist
    loaded = load_state(cid)
    assert loaded is not None
    assert loaded.current_step is None


def test_archive_download(client: TestClient, bucket: Path) -> None:
    cid = _character_with_prop()
    res = client.get(f"/api/character/{cid}/archive")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/zip"
    assert res.content[:2] == b"PK"  # zip magic


def test_finish_and_archive_404(client: TestClient) -> None:
    assert client.post("/api/character/ghost/finish").status_code == 404
    assert client.get("/api/character/ghost/archive").status_code == 404


# --------------------------------------------------------------------------- #
# project STYLE: refs upload + auto-draft + edit + lock + reset
# --------------------------------------------------------------------------- #
def _png_bytes() -> bytes:
    """A small but real PNG (so the server-side thumbnail path can decode it)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (120, 90, 60)).save(buf, format="PNG")
    return buf.getvalue()


def _img_files(n: int) -> list[tuple[str, tuple[str, bytes, str]]]:
    """Multipart ``files=`` payload of ``n`` real PNG uploads."""
    return [("files", (f"r{i}.png", _png_bytes(), "image/png")) for i in range(n)]


def test_style_empty(client: TestClient, bucket: Path) -> None:
    assert client.get("/api/style").json()["style"] == {
        "prompt": "",
        "approved": False,
        "ref_keys": [],
        "ref_count": 0,
        "locked": False,
    }


def test_style_upload_drafts_on_fifth(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        webapp, "draft_style_prompt", lambda paths, meter=None: "inked comic, muted watercolour"
    )
    four = client.post("/api/style/refs", files=_img_files(4)).json()
    assert four["drafted"] is False
    assert four["style"]["ref_count"] == 4
    assert four["style"]["prompt"] == ""
    fifth = client.post("/api/style/refs", files=_img_files(1)).json()
    assert fifth["drafted"] is True
    assert fifth["style"]["prompt"] == "inked comic, muted watercolour"
    assert fifth["style"]["approved"] is True
    assert fifth["style"]["ref_count"] == 5
    assert client.get("/api/style/ref/ref_1").status_code == 200


def test_style_put_then_locked(client: TestClient, bucket: Path) -> None:
    edited = client.put("/api/style", json={"prompt": "hand-drawn ink"}).json()
    assert edited["style"]["prompt"] == "hand-drawn ink"
    # lock it with a character that already has a generated frame
    state = blank_state("Локи")
    state.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    save_state(state)
    assert client.get("/api/style").json()["style"]["locked"] is True
    assert client.put("/api/style", json={"prompt": "x"}).status_code == 409


def test_style_reset(client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(webapp, "draft_style_prompt", lambda paths, meter=None: "drafted style")
    client.post("/api/style/refs", files=_img_files(5))
    assert client.get("/api/style").json()["style"]["prompt"] == "drafted style"
    reset = client.post("/api/style/reset").json()
    assert reset["style"]["prompt"] == ""
    assert reset["style"]["ref_count"] == 0


def test_style_refs_empty_upload_ok(client: TestClient, bucket: Path) -> None:
    # An empty multipart upload is a no-op (used to trigger a draft when refs
    # already sit in the bucket) — it must not error.
    assert client.post("/api/style/refs", files=_img_files(0)).status_code == 200


def test_style_ref_bad_and_missing(client: TestClient, bucket: Path) -> None:
    assert client.get("/api/style/ref/bad-key").status_code == 400
    assert client.get("/api/style/ref/ref_9").status_code == 404


def test_style_ref_thumbnail(client: TestClient, bucket: Path) -> None:
    client.post("/api/style/refs", files=_img_files(1))
    full = client.get("/api/style/ref/ref_1")
    thumb = client.get("/api/style/ref/ref_1", params={"w": 16})
    assert full.status_code == 200
    assert thumb.status_code == 200
    assert thumb.headers["content-type"] == "image/jpeg"  # downscaled, not the raw PNG
    assert "max-age" in thumb.headers.get("cache-control", "")


def test_create_character_stamps_project_style(
    client: TestClient, bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.put("/api/style", json={"prompt": "frozen project style"})
    _seed_extracted(client, monkeypatch)
    cid = client.post("/api/character", json={"name": "Герон"}).json()["character"]["id"]
    loaded = load_state(cid)
    assert loaded is not None
    assert loaded.prompt_layers.style == "frozen project style"
