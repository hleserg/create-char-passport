"""Tests for the passport screen — session handlers + the refresh glue."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.screens.views import (
    PASSPORT_REFRESH_KEYS,
    passport_refresh,
    render_passport,
)
from create_char_passport.state import CharacterState, StepRecord, blank_state
from create_char_passport.storage import character_dir, load_state, save_state
from create_char_passport.wizard import passport


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def _fake_ok(prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    Path(output_path).write_bytes(b"img")
    if meter is not None:
        meter.image_usd += 0.05
        meter.image_calls += 1
    return GenerationResult(image_path=str(output_path), ok=True)


def _fake_fail(prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    return GenerationResult(image_path=None, ok=False, error="rate limited — retry")


def _started(
    bucket: Path, screen: ScreenId = ScreenId.PASSPORT
) -> tuple[WizardSession, CharacterState]:
    """A session on ``screen`` with a fresh saved character (narrowed, non-None)."""
    state = blank_state("Heron")
    save_state(state)
    return WizardSession(current_screen=screen, character=state), state


# --------------------------------------------------------------------------- #
# Enter / edit
# --------------------------------------------------------------------------- #
def test_on_enter_passport_places_cursor_and_honours_gate(bucket: Path) -> None:
    session, char = _started(bucket)
    char.steps["passport_profile"] = StepRecord(need_regen=True)
    handlers.on_enter_passport(session)
    assert char.current_step == "passport_profile"


def test_on_enter_passport_noop_off_screen(bucket: Path) -> None:
    session, char = _started(bucket, screen=ScreenId.CHAR_DATA)
    char.current_step = None
    handlers.on_enter_passport(session)
    assert char.current_step is None


def test_passport_handlers_noop_without_character() -> None:
    session = WizardSession(current_screen=ScreenId.PASSPORT)  # no character picked yet
    assert handlers.on_enter_passport(session).character is None
    assert handlers.on_passport_edit(session, "", "", "").character is None
    assert handlers.on_passport_generate(session, "", "", "").character is None
    assert handlers.on_passport_approve(session).character is None
    assert handlers.on_passport_back(session).character is None
    assert handlers.on_passport_forward(session).character is None


def test_on_passport_edit_persists_editable_layer(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    handlers.on_passport_edit(session, face="broad nose", body="ignored", outfit="tunic")
    assert char.prompt_layers.face == "broad nose"
    assert char.base_outfit.prompt == "tunic"
    assert char.prompt_layers.body == ""  # body frozen on frame 1


# --------------------------------------------------------------------------- #
# Generate
# --------------------------------------------------------------------------- #
def test_on_passport_generate_success_bills_cost(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(passport, "generate_image", _fake_ok)
    session, char = _started(bucket)
    char.current_step = "passport_face"
    out = handlers.on_passport_generate(session, face="nose", body="", outfit="tunic")
    assert "Утвердить" in out.notice
    assert out.cost.image_calls == 1  # session billed
    assert char.cost.image_calls == 1  # character billed
    assert char.steps["passport_face"].last_path == "refs/passport_face.png"


def test_on_passport_generate_failure_keeps_prompt_no_cost(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(passport, "generate_image", _fake_fail)
    session, char = _started(bucket)
    char.current_step = "passport_face"
    out = handlers.on_passport_generate(session, face="nose", body="", outfit="tunic")
    assert "retry" in out.notice.lower()
    assert out.cost.image_calls == 0  # failed call is never billed
    assert char.prompt_layers.face == "nose"  # prompt preserved


# --------------------------------------------------------------------------- #
# Approve
# --------------------------------------------------------------------------- #
def test_on_passport_approve_advances_cursor(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    char.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    handlers.on_passport_approve(session)
    assert char.steps["passport_face"].approved_path == "refs/passport_face.png"
    assert char.current_step == "passport_body"


def test_on_passport_approve_without_generation_notices(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    out = handlers.on_passport_approve(session)
    assert "Сначала сгенерируйте" in out.notice
    record = char.steps.get("passport_face")
    assert record is None or record.approved_path is None


def test_on_passport_approve_last_frame_announces_complete(bucket: Path) -> None:
    session, char = _started(bucket)
    for key in ("passport_face", "passport_body", "passport_profile", "passport_back"):
        char.steps[key] = StepRecord(approved_path=f"refs/{key}.png")
    char.current_step = "passport_3q"
    char.steps["passport_3q"] = StepRecord(last_path="refs/passport_3q.png")
    out = handlers.on_passport_approve(session)
    assert "Все 5" in out.notice


# --------------------------------------------------------------------------- #
# Back / forward
# --------------------------------------------------------------------------- #
def test_on_passport_back_steps_through_frames(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_body"
    out = handlers.on_passport_back(session)
    assert char.current_step == "passport_face"
    assert out.current_screen is ScreenId.PASSPORT  # still in phase


def test_on_passport_back_from_first_frame_leaves_phase(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    out = handlers.on_passport_back(session)
    assert out.current_screen is ScreenId.CHAR_DATA


def test_on_passport_forward_blocked_until_approved(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    char.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    out = handlers.on_passport_forward(session)
    assert out.current_screen is ScreenId.PASSPORT  # not advanced
    assert "Утвердите" in out.notice


def test_on_passport_forward_advances_when_approved(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    char.steps["passport_face"] = StepRecord(approved_path="refs/passport_face.png")
    handlers.on_passport_forward(session)
    assert char.current_step == "passport_body"


def test_on_passport_forward_exits_phase_when_all_approved(bucket: Path) -> None:
    session, char = _started(bucket)
    for key in (
        "passport_face",
        "passport_body",
        "passport_profile",
        "passport_back",
        "passport_3q",
    ):
        char.steps[key] = StepRecord(approved_path=f"refs/{key}.png")
    char.current_step = "passport_3q"
    out = handlers.on_passport_forward(session)
    # No optional phases enabled → next phase after passport is the dataset.
    assert out.current_screen is ScreenId.DATASET


def test_on_passport_forward_last_frame_not_all_approved_notices(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_3q"
    char.steps["passport_3q"] = StepRecord(approved_path="refs/passport_3q.png")
    out = handlers.on_passport_forward(session)
    assert out.current_screen is ScreenId.PASSPORT
    assert "все 5" in out.notice.lower()


def test_on_passport_forward_blocked_when_last_frame_needs_regen(bucket: Path) -> None:
    session, char = _started(bucket)
    for key in (
        "passport_face",
        "passport_body",
        "passport_profile",
        "passport_back",
        "passport_3q",
    ):
        char.steps[key] = StepRecord(approved_path=f"refs/{key}.png")
    # The last frame itself is flagged need_regen: the gate must still block the
    # forward exit even though all five have an approved_path (the discriminating case).
    char.steps["passport_3q"].need_regen = True
    char.current_step = "passport_3q"
    out = handlers.on_passport_forward(session)
    assert out.current_screen is ScreenId.PASSPORT  # need_regen conjunct blocks exit
    assert "все 5" in out.notice.lower()


# --------------------------------------------------------------------------- #
# Persistence (state.json round-trip)
# --------------------------------------------------------------------------- #
def test_on_passport_approve_persists_to_disk(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    char.steps["passport_face"] = StepRecord(last_path="refs/passport_face.png")
    handlers.on_passport_approve(session)
    reloaded = load_state(char.character_id)
    assert reloaded is not None
    assert reloaded.steps["passport_face"].approved_path == "refs/passport_face.png"
    assert reloaded.current_step == "passport_body"  # cursor advance persisted


def test_stale_flag_round_trips_through_disk(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(passport, "generate_image", _fake_ok)
    session, char = _started(bucket)
    cdir = character_dir(char.character_id)
    for key in ("passport_face", "passport_body", "passport_profile"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        char.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    char.current_step = "passport_face"
    handlers.on_passport_generate(session, face="nose", body="", outfit="tunic")  # regen FACE
    assert char.steps["passport_profile"].stale is True
    reloaded = load_state(char.character_id)
    assert reloaded is not None
    assert reloaded.steps["passport_profile"].stale is True  # serialization round-trip


# --------------------------------------------------------------------------- #
# Refresh glue
# --------------------------------------------------------------------------- #
def test_passport_refresh_none_is_all_noop() -> None:
    updates = passport_refresh(WizardSession())
    assert len(updates) == len(PASSPORT_REFRESH_KEYS)
    assert all(upd == {"__type__": "update"} for upd in updates)


def test_passport_refresh_frame_one_interactivity(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    upd = dict(zip(PASSPORT_REFRESH_KEYS, passport_refresh(session), strict=True))
    assert "Фас-портрет" in upd["heading"]["value"]
    assert upd["face_box"]["interactive"] is True
    assert upd["body_box"]["interactive"] is False  # frozen on frame 1
    assert upd["outfit_box"]["interactive"] is True
    assert upd["expression_box"]["value"] == "neutral"  # K3 forced
    assert upd["composition_box"]["value"]  # scene preset injected
    assert upd["gen_btn"]["value"] == "Сгенерировать"  # no generation yet
    assert upd["approve_btn"]["interactive"] is False
    assert upd["forward_btn"]["interactive"] is False
    assert upd["cascade"]["visible"] is False


def test_passport_refresh_regenerate_label_and_preview(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_face"
    char_dir = character_dir(char.character_id)
    (char_dir / "refs/passport_face.png").write_bytes(b"img")
    char.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png", approved_path="refs/passport_face.png"
    )
    upd = dict(zip(PASSPORT_REFRESH_KEYS, passport_refresh(session), strict=True))
    assert upd["gen_btn"]["value"] == "Перегенерить"  # a generation exists
    assert upd["approve_btn"]["interactive"] is True
    assert upd["forward_btn"]["interactive"] is True  # approved
    assert upd["preview"]["value"] == str(char_dir / "refs/passport_face.png")


def test_passport_refresh_shows_cascade_when_stale(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_profile"
    char.steps["passport_profile"] = StepRecord(
        approved_path="refs/passport_profile.png", stale=True
    )
    upd = dict(zip(PASSPORT_REFRESH_KEYS, passport_refresh(session), strict=True))
    assert upd["cascade"]["visible"] is True
    assert "разъехаться" in upd["cascade"]["value"]


def test_passport_refresh_freezes_face_body_on_later_frames(bucket: Path) -> None:
    session, char = _started(bucket)
    char.current_step = "passport_3q"
    upd = dict(zip(PASSPORT_REFRESH_KEYS, passport_refresh(session), strict=True))
    assert upd["face_box"]["interactive"] is False
    assert upd["body_box"]["interactive"] is False
    assert upd["outfit_box"]["interactive"] is False


def test_render_passport_exposes_slots_and_components() -> None:
    import gradio as gr

    with gr.Blocks():
        handle = render_passport()
    assert handle.prompt is not None
    assert handle.ai_check is not None
    assert handle.ai_edit is not None
    assert handle.ai_check.context.step_key == "passport_face"
    for key in PASSPORT_REFRESH_KEYS:
        assert key in handle.components
