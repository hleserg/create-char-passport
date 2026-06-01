"""Tests for the pure session handlers (start / style / char-data screens)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.state import blank_state
from create_char_passport.storage import load_state, save_state
from create_char_passport.wizard import ExtractedCharacter


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Point the storage bucket at a temp dir so handlers can persist freely."""
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def _session_with_extracted() -> WizardSession:
    session = WizardSession()
    session.extracted_characters = [
        ExtractedCharacter(name="Conan", table={"gender": "male"}),
        ExtractedCharacter(name="Tyra", table={}),
    ]
    return session


# --------------------------------------------------------------------------- #
# Start screen
# --------------------------------------------------------------------------- #
def test_on_extract_populates_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        handlers, "extract_characters", lambda text, meter=None: [ExtractedCharacter(name="Conan")]
    )
    session = handlers.on_extract(WizardSession(), "a story")
    assert [c.name for c in session.extracted_characters] == ["Conan"]
    assert "Extracted 1" in session.notice


def test_on_extract_none_found(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(handlers, "extract_characters", lambda text, meter=None: [])
    session = handlers.on_extract(WizardSession(), "")
    assert session.extracted_characters == []
    assert "No characters" in session.notice


def test_on_extract_accrues_session_cost(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_extract(text: str, meter: object = None) -> list[ExtractedCharacter]:
        meter.llm_usd += 0.0021  # type: ignore[union-attr]
        meter.llm_calls += 1  # type: ignore[union-attr]
        return [ExtractedCharacter(name="Conan")]

    monkeypatch.setattr(handlers, "extract_characters", fake_extract)
    session = handlers.on_extract(WizardSession(), "a story")
    # No character yet -> spend lands on the session ledger only.
    assert session.cost.llm_calls == 1
    assert session.cost.total_usd == pytest.approx(0.0021)


def test_on_extract_does_not_bill_an_incidentally_loaded_character(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extraction is cross-character — it must never inflate a loaded character."""

    def fake_extract(text: str, meter: object = None) -> list[ExtractedCharacter]:
        meter.llm_usd += 0.0021  # type: ignore[union-attr]
        meter.llm_calls += 1  # type: ignore[union-attr]
        return [ExtractedCharacter(name="Tyra")]

    monkeypatch.setattr(handlers, "extract_characters", fake_extract)
    session = WizardSession()
    session.character = blank_state("Conan")  # a character happens to be loaded

    session = handlers.on_extract(session, "a story")

    assert session.cost.total_usd == pytest.approx(0.0021)  # session billed
    assert session.character is not None
    assert session.character.cost.total_usd == 0.0  # character NOT billed


def test_pick_extracted_goes_to_style_when_unapproved(bucket: Path) -> None:
    session = _session_with_extracted()
    out = handlers.on_pick_extracted(session, "Conan")
    assert out.character is not None
    assert out.character.name == "Conan"
    assert out.current_screen is ScreenId.STYLE
    # No persistence until style is settled.
    assert not (bucket / "conan").exists()


def test_pick_extracted_goes_to_char_data_when_style_approved(bucket: Path) -> None:
    session = _session_with_extracted()
    session.style_approved = True
    session.style_prompt = "inked comic"
    out = handlers.on_pick_extracted(session, "Conan")
    assert out.current_screen is ScreenId.CHAR_DATA
    assert out.character is not None
    assert out.character.prompt_layers.style == "inked comic"
    saved = load_state("conan")
    assert saved is not None and saved.name == "Conan"


def test_pick_extracted_unknown_name_is_noop() -> None:
    session = _session_with_extracted()
    out = handlers.on_pick_extracted(session, "Nobody")
    assert out.character is None
    assert out.current_screen is ScreenId.HOME


def test_open_saved_resumes_unfinished(bucket: Path) -> None:
    state = blank_state("Conan")
    state.current_step = "passport_face"
    save_state(state)
    out = handlers.on_open_saved(WizardSession(), "conan")
    assert out.character is not None
    assert out.current_screen is ScreenId.PASSPORT


def test_open_saved_finished_goes_to_char_data_and_detects_style(bucket: Path) -> None:
    state = blank_state("Lucius")
    state.current_step = None
    state.prompt_layers.style = "painted illustration"
    save_state(state)
    out = handlers.on_open_saved(WizardSession(), "lucius")
    assert out.current_screen is ScreenId.CHAR_DATA
    assert out.style_approved is True
    assert out.style_prompt == "painted illustration"


def test_open_saved_missing(bucket: Path) -> None:
    out = handlers.on_open_saved(WizardSession(), "ghost")
    assert out.character is None
    assert "Could not open" in out.notice


def test_open_saved_character_helper(bucket: Path) -> None:
    assert handlers.open_saved_character("ghost") is None
    save_state(blank_state("Conan"))
    loaded = handlers.open_saved_character("conan")
    assert loaded is not None
    _state, screen = loaded
    assert screen is ScreenId.CHAR_DATA


# --------------------------------------------------------------------------- #
# Style screen
# --------------------------------------------------------------------------- #
def test_on_draft_style_delegates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        handlers, "draft_style_prompt", lambda paths, meter=None: f"drafted:{len(paths)}"
    )
    _session, text = handlers.on_draft_style(WizardSession(), ["a.png", "b.png"])
    assert text == "drafted:2"
    _session2, text_none = handlers.on_draft_style(WizardSession(), None)
    assert text_none == "drafted:0"


def test_on_draft_style_bills_active_character(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")

    def fake_draft(paths: list[str], meter: object = None) -> str:
        meter.llm_usd += 0.005  # type: ignore[union-attr]
        meter.llm_calls += 1  # type: ignore[union-attr]
        return "inked comic"

    monkeypatch.setattr(handlers, "draft_style_prompt", fake_draft)
    out, _text = handlers.on_draft_style(session, ["a.png"])

    assert out.character is not None
    assert out.character.cost.total_usd == pytest.approx(0.005)
    assert out.cost.total_usd == pytest.approx(0.005)
    # Persisted to state.json so it survives a reopen.
    saved = load_state("conan")
    assert saved is not None
    assert saved.cost.total_usd == pytest.approx(0.005)


def test_approve_style_freezes_and_advances(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")
    out = handlers.on_approve_style(session, "  inked comic  ")
    assert out.style_approved is True
    assert out.style_prompt == "inked comic"
    assert out.character is not None
    assert out.character.prompt_layers.style == "inked comic"
    assert out.current_screen is ScreenId.CHAR_DATA
    assert load_state("conan") is not None


def test_approve_style_without_character_returns_home() -> None:
    out = handlers.on_approve_style(WizardSession(), "x")
    assert out.current_screen is ScreenId.HOME
    assert out.style_approved is True


# --------------------------------------------------------------------------- #
# Character-data screen
# --------------------------------------------------------------------------- #
def test_char_data_mutators_persist(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")

    handlers.on_update_table(session, {"gender": "male", "age": "30"})
    handlers.on_toggle_emotions(session, True)
    handlers.on_update_base_emotion(session, True, "grim, brooding")
    handlers.on_toggle_outfits(session, True)
    handlers.on_update_outfits(session, [["plate armor", True]])
    handlers.on_toggle_props(session, True)
    handlers.on_update_props(session, {"data": [["sword"]]})

    saved = load_state("conan")
    assert saved is not None
    assert saved.character_table["gender"] == "male"
    assert saved.emotions.enabled is True
    assert saved.emotions.base_emotion.value == "grim, brooding"
    assert saved.outfits_enabled is True
    assert saved.outfits[0].prompt == "plate armor"
    assert saved.props_enabled is True
    assert saved.props[0].name == "sword"


def test_char_data_mutators_noop_without_character() -> None:
    session = WizardSession()
    # None of these should raise when there is no character yet.
    handlers.on_update_table(session, {"gender": "male"})
    handlers.on_toggle_emotions(session, True)
    handlers.on_update_base_emotion(session, True, "grim")
    handlers.on_toggle_outfits(session, True)
    handlers.on_update_outfits(session, [["x", False]])
    handlers.on_toggle_props(session, True)
    handlers.on_update_props(session, [["y"]])
    assert session.character is None


def test_on_next_advances_char_data_to_passport(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")
    session.current_screen = ScreenId.CHAR_DATA
    out = handlers.on_next(session)
    assert out.current_screen is ScreenId.PASSPORT


def test_on_back_steps_back() -> None:
    session = WizardSession()
    session.current_screen = ScreenId.CHAR_DATA
    out = handlers.on_back(session)
    assert out.current_screen is ScreenId.STYLE


def test_rows_coercion_handles_dict_and_garbage(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")
    handlers.on_update_outfits(session, "not-a-list")
    assert session.character.outfits == []


# --------------------------------------------------------------------------- #
# Scene editing (COMPOSITION override)
# --------------------------------------------------------------------------- #
def test_on_set_and_clear_scene_override_persist(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")

    handlers.on_set_scene_override(session, "front_portrait", "tight crop, eye level")
    saved = load_state("conan")
    assert saved is not None
    assert saved.scene_overrides == {"front_portrait": "tight crop, eye level"}

    handlers.on_clear_scene_override(session, "front_portrait")
    saved = load_state("conan")
    assert saved is not None
    assert saved.scene_overrides == {}


def test_scene_override_handlers_noop_without_character() -> None:
    session = WizardSession()
    handlers.on_set_scene_override(session, "front_portrait", "x")
    handlers.on_clear_scene_override(session, "front_portrait")
    assert session.character is None
