"""Tests for the AI-assist wiring glue + check handlers (HLE-731).

The glue's output arity is asserted directly here because Gradio only validates
``.click()`` input/output counts at call time — ``build_demo`` rendering does
NOT catch a mismatched output list, so these stand in for that.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.ai import wiring
from create_char_passport.ai.review import CheckOutcome
from create_char_passport.config import get_settings
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.state import OutfitEntry, blank_state
from create_char_passport.storage import save_state


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    monkeypatch.setenv("APP_GEMINI_API_KEY", "")  # no key → call_llm fails softly
    get_settings.cache_clear()
    yield tmp_path


# --------------------------------------------------------------------------- #
# Glue arity — must match the wired output lists in wire_check_slot
# --------------------------------------------------------------------------- #
def test_check_result_updates_arity_and_visibility() -> None:
    assert len(wiring.check_result_updates(None)) == 4
    with_prompt = wiring.check_result_updates(CheckOutcome("ок", "new prompt", "passport_face"))
    assert len(with_prompt) == 4
    assert with_prompt[1]["visible"] is True  # proposed box shown
    assert with_prompt[2]["visible"] is True  # accept button shown
    no_prompt = wiring.check_result_updates(
        CheckOutcome("ок, ничего не меняй", None, "passport_face")
    )
    assert no_prompt[2]["visible"] is False  # accept hidden when there is no new prompt


def test_hidden_panel_arity() -> None:
    panel = wiring.hidden_panel()
    assert len(panel) == 4
    assert all(u["visible"] is False for u in panel)


def test_on_check_returns_six_outputs(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # check_btn.click outputs = [session, result, proposed, accept, reject, cost_banner] = 6.
    monkeypatch.setattr(
        handlers, "check_step", lambda *a, **k: CheckOutcome("ок", "better", "passport_face")
    )
    state = blank_state("Conan")
    save_state(state)
    session = WizardSession(current_screen=ScreenId.PASSPORT, character=state)
    out = wiring._on_check("passport_face", None, session)
    assert len(out) == 6
    assert out[0] is session  # first output is the session


def test_on_accept_returns_session_and_writes(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    session = WizardSession(character=state)
    assert wiring._on_accept("passport_face", None, session, "rugged face") is session
    assert state.prompt_layers.face == "rugged face"


# --------------------------------------------------------------------------- #
# Resolver + handlers
# --------------------------------------------------------------------------- #
def test_resolve_check_key_real_and_placeholders(bucket: Path) -> None:
    state = blank_state("Conan")
    assert handlers._resolve_check_key(state, "passport_face", None) == "passport_face"
    state.dataset_compositions = ["a"]
    state.current_step = "dataset_0"
    assert handlers._resolve_check_key(state, "dataset_step", None) == "dataset_0"
    state.outfits.append(OutfitEntry(id="7"))
    state.current_step = "outfit_7"
    assert handlers._resolve_check_key(state, "outfit_step", None) == "outfit_7"
    assert handlers._resolve_check_key(state, "outfit_detail_step", 0) == "outfit_7_detail_1"


def test_resolve_check_key_no_cursor_is_none(bucket: Path) -> None:
    state = blank_state("Conan")
    assert handlers._resolve_check_key(state, "dataset_step", None) is None
    assert handlers._resolve_check_key(state, "outfit_step", None) is None
    assert handlers._resolve_check_key(state, "prop_shot_step", 0) is None


def test_run_ai_check_no_character() -> None:
    assert handlers.run_ai_check(WizardSession(), "passport_face") is None


def test_accept_ai_check_writes_via_cursor(bucket: Path) -> None:
    state = blank_state("Conan")
    state.dataset_compositions = ["old pose"]
    state.current_step = "dataset_0"
    save_state(state)
    session = WizardSession(character=state)
    handlers.accept_ai_check(session, "dataset_step", None, "full body, crouching")
    assert state.dataset_compositions[0] == "full body, crouching"
