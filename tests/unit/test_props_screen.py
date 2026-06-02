"""Tests for the props screen — session handlers + the refresh glue."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.screens.views import PROPS_REFRESH_KEYS, props_refresh, render_props
from create_char_passport.state import CharacterState, PropEntry, PropShot, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import generation


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
    return GenerationResult(image_path=None, ok=False, error="boom — retry")


def _started(bucket: Path, *, n: int = 1, shots: int = 1) -> tuple[WizardSession, CharacterState]:
    state = blank_state("Conan")
    state.props_enabled = True
    state.props = [
        PropEntry(id=str(i + 1), name=f"prop {i + 1}", shots=[PropShot() for _ in range(shots)])
        for i in range(n)
    ]
    save_state(state)
    session = WizardSession(current_screen=ScreenId.PROPS, character=state)
    handlers.on_enter_props(session)
    return session, state


# --------------------------------------------------------------------------- #
# Enter / guards
# --------------------------------------------------------------------------- #
def test_on_enter_props_seeds_first(bucket: Path) -> None:
    _session, char = _started(bucket, n=2)
    assert char.current_step == "prop_1_shot_1"


def test_on_enter_props_preserves_resumed_cursor(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    char.current_step = "prop_2_shot_1"
    handlers.on_enter_props(session)
    assert char.current_step == "prop_2_shot_1"


def test_prop_handlers_noop_without_character() -> None:
    session = WizardSession(current_screen=ScreenId.PROPS)
    assert handlers.on_enter_props(session).character is None
    assert handlers.on_prop_shot_generate(session, 0).character is None
    assert handlers.on_prop_add_shot(session).character is None
    assert handlers.on_props_forward(session).current_screen is not ScreenId.PROPS


# --------------------------------------------------------------------------- #
# Generate + edits
# --------------------------------------------------------------------------- #
def test_on_prop_shot_generate_sets_ref_and_bills(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    out = handlers.on_prop_shot_generate(session, 0)
    assert char.props[0].shots[0].ref == "refs/prop_1_shot_1.png"
    assert out.cost.image_calls == 1
    assert char.cost.image_calls == 1


def test_on_prop_shot_generate_failure_no_bill(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    session, char = _started(bucket)
    out = handlers.on_prop_shot_generate(session, 0)
    assert char.props[0].shots[0].ref is None
    assert out.cost.image_calls == 0
    assert "boom" in out.notice


def test_prop_shot_what_and_prompt_edit_persist(bucket: Path) -> None:
    session, char = _started(bucket)
    handlers.on_prop_shot_what_edit(session, "  a glowing sword  ", j=0)
    handlers.on_prop_shot_prompt_edit(session, "  rune-etched longsword  ", j=0)
    assert char.props[0].shots[0].what == "a glowing sword"
    assert char.props[0].shots[0].prompt == "rune-etched longsword"


# --------------------------------------------------------------------------- #
# Add / delete shots
# --------------------------------------------------------------------------- #
def test_add_and_delete_shot_flow(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket, shots=1)
    handlers.on_prop_add_shot(session)
    assert len(char.props[0].shots) == 2
    handlers.on_prop_shot_generate(session, 1)
    handlers.on_prop_delete_shot(session, 1)  # generated → confirm first
    assert session.prop_pending_delete == (0, 2)
    assert len(char.props[0].shots) == 2
    handlers.on_prop_delete_shot_confirmed(session, 1)
    assert len(char.props[0].shots) == 1
    assert session.prop_pending_delete is None


def test_delete_ungenerated_shot_immediate(bucket: Path) -> None:
    session, char = _started(bucket, shots=2)
    handlers.on_prop_delete_shot(session, 1)
    assert len(char.props[0].shots) == 1
    assert session.prop_pending_delete is None


# --------------------------------------------------------------------------- #
# Forward / back navigation (ungated — props are optional)
# --------------------------------------------------------------------------- #
def test_forward_advances_to_next_prop_then_leaves(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    out = handlers.on_props_forward(session)
    assert out.current_screen is ScreenId.PROPS
    assert char.current_step == "prop_2_shot_1"
    out = handlers.on_props_forward(session)
    assert out.current_screen is ScreenId.DATASET  # props is the last optional phase


def test_back_steps_between_props_then_out(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    char.current_step = "prop_2_shot_1"
    handlers.on_props_back(session)
    assert char.current_step == "prop_1_shot_1"
    out = handlers.on_props_back(session)
    assert out.current_screen is not ScreenId.PROPS


# --------------------------------------------------------------------------- #
# Refresh glue
# --------------------------------------------------------------------------- #
def test_props_refresh_none_is_all_noop() -> None:
    updates = props_refresh(WizardSession())
    assert len(updates) == len(PROPS_REFRESH_KEYS)


def test_props_refresh_populates_and_caps_add(bucket: Path) -> None:
    session, char = _started(bucket, shots=1)
    cdir = character_dir(char.character_id)
    (cdir / "refs/prop_1_shot_1.png").write_bytes(b"img")
    char.props[0].shots[0].ref = "refs/prop_1_shot_1.png"
    char.props[0].shots[0].what = "sword"
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert "prop 1" in upd["prop_label"]["value"]
    assert upd["shot_cell_0"]["visible"] is True
    assert upd["shot_cell_1"]["visible"] is False  # only one shot
    assert upd["shot_what_0"]["value"] == "sword"
    assert upd["shot_preview_0"]["value"] == str(cdir / "refs/prop_1_shot_1.png")
    assert upd["add_shot_btn"]["interactive"] is True  # 1 < 3


def test_props_refresh_add_disabled_at_cap(bucket: Path) -> None:
    session, _char = _started(bucket, shots=3)
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert upd["add_shot_btn"]["interactive"] is False


def test_render_props_components_and_slot() -> None:
    import gradio as gr

    with gr.Blocks():
        handle = render_props()
    assert handle.ai_check is not None
    assert handle.ai_edit is None
    assert handle.ai_check.context.step_key == "prop_shot_step"
    for key in PROPS_REFRESH_KEYS:
        assert key in handle.components
