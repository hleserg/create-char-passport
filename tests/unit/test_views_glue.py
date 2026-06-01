"""Tests for the Gradio session->update glue helpers in views."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.screens.router import SCREEN_ORDER, ScreenId, WizardSession
from create_char_passport.screens.views import (
    CHAR_DATA_REFRESH_KEYS,
    char_data_refresh,
    cost_banner_text,
    home_refresh,
    interactive_update,
    saved_choices,
    screen_visibility,
    update_table_fields,
)
from create_char_passport.state import CHARACTER_TABLE_KEYS, CostLedger, blank_state
from create_char_passport.storage import save_state
from create_char_passport.wizard import ExtractedCharacter


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def test_screen_visibility_only_current_visible() -> None:
    session = WizardSession()
    session.current_screen = ScreenId.CHAR_DATA
    updates = screen_visibility(session)
    visible = {screen for screen, upd in zip(SCREEN_ORDER, updates, strict=True) if upd["visible"]}
    assert visible == {ScreenId.CHAR_DATA}


def test_home_refresh_lists_extracted_and_saved(bucket: Path) -> None:
    save_state(blank_state("Lucius"))
    session = WizardSession()
    session.notice = "Extracted 2 character(s)."
    session.extracted_characters = [
        ExtractedCharacter(name="Conan"),
        ExtractedCharacter(name="Tyra"),
    ]
    notice, extracted, saved = home_refresh(session)
    assert notice["value"] == "Extracted 2 character(s)."
    assert extracted["choices"] == ["Conan", "Tyra"]
    assert extracted["value"] == "Conan"
    assert ("Lucius — ready", "lucius") in saved["choices"]


def test_home_refresh_empty(bucket: Path) -> None:
    _notice, extracted, saved = home_refresh(WizardSession())
    assert extracted["value"] is None
    assert saved["value"] is None


def test_saved_choices_pairs(bucket: Path) -> None:
    save_state(blank_state("Conan"))
    choices = saved_choices()
    assert choices == [("Conan — ready", "conan")]


def test_char_data_refresh_none_is_all_noop() -> None:
    updates = char_data_refresh(WizardSession())
    assert len(updates) == len(CHAR_DATA_REFRESH_KEYS)
    assert all(upd == {"__type__": "update"} for upd in updates)


def test_char_data_refresh_populates_fields() -> None:
    state = blank_state("Conan")
    state.character_table = {"gender": "male", "details": "scar"}
    state.emotions.enabled = True
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "grim, brooding"
    state.outfits_enabled = True
    session = WizardSession()
    session.character = state

    updates = dict(zip(CHAR_DATA_REFRESH_KEYS, char_data_refresh(session), strict=True))
    assert "Conan" in updates["char_title"]["value"]
    assert updates["table_gender"]["value"] == "male"
    assert updates["table_details"]["value"] == "scar"
    assert updates["table_age"]["value"] == ""
    assert updates["emotions_enabled"]["value"] is True
    assert updates["emotion_table"]["interactive"] is True
    assert updates["base_emotion_value"]["value"] == "grim, brooding"
    assert updates["outfit_table"]["interactive"] is True
    assert updates["prop_table"]["interactive"] is False


def test_update_table_fields_zips_values(bucket: Path) -> None:
    session = WizardSession()
    session.character = blank_state("Conan")
    values = ["male", "30", "stocky", "black", "blue", "tanned", "warrior", "scar"]
    out = update_table_fields(session, *values)
    assert out.character is not None
    table = out.character.character_table
    for key, value in zip(CHARACTER_TABLE_KEYS, values, strict=True):
        assert table[key] == value


def test_interactive_update() -> None:
    assert interactive_update(True)["interactive"] is True
    assert interactive_update(False)["interactive"] is False


def test_cost_banner_session_only_when_no_character() -> None:
    session = WizardSession()
    session.cost.merge(CostLedger(llm_usd=0.0123, llm_calls=1))
    text = cost_banner_text(session)
    assert "Сессия" in text
    assert "0.0123" in text
    assert "Персонаж" not in text


def test_cost_banner_shows_character_and_session() -> None:
    session = WizardSession()
    session.character = blank_state("Conan")
    session.character.cost.merge(CostLedger(image_usd=0.05, image_calls=1))
    session.cost.merge(CostLedger(image_usd=0.05, llm_usd=0.01, image_calls=1, llm_calls=1))
    text = cost_banner_text(session)
    assert "Персонаж «Conan»" in text
    assert "0.0500" in text  # character total
    assert "0.0600" in text  # session total
