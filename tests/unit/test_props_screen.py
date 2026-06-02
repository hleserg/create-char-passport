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


def test_props_refresh_delete_confirm_visibility(bucket: Path) -> None:
    session, _char = _started(bucket, shots=2)
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert upd["shot_delete_confirm_0"]["visible"] is False  # no pending delete
    session.prop_pending_delete = (0, 1)  # 1-based shot n → 0-based cell 0
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert upd["shot_delete_confirm_0"]["visible"] is True
    assert upd["shot_delete_confirm_1"]["visible"] is False


def test_props_refresh_missing_ref_file_yields_no_preview(bucket: Path) -> None:
    session, char = _started(bucket, shots=1)
    char.props[0].shots[0].ref = "refs/prop_1_shot_1.png"  # ref set, file NOT written
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert upd["shot_preview_0"]["value"] is None


def test_prop_born_with_one_shot_via_sync(bucket: Path) -> None:
    # A prop created through the real data-table path is born with one shot, so
    # the props screen shows a usable shot cell immediately (§5).
    from create_char_passport.wizard.forms import set_props_enabled, sync_props

    state = blank_state("Conan")
    set_props_enabled(state, True)
    sync_props(state, [["sword"]])
    assert len(state.props[0].shots) == 1
    session = WizardSession(current_screen=ScreenId.PROPS, character=state)
    handlers.on_enter_props(session)
    upd = dict(zip(PROPS_REFRESH_KEYS, props_refresh(session), strict=True))
    assert upd["shot_cell_0"]["visible"] is True


def test_props_back_to_outfits_lands_usable(bucket: Path) -> None:
    # Backing out of the first prop must leave a usable OUTFITS cursor (the
    # back chain re-seeds it via on_enter_outfits), not a dead one.
    from create_char_passport.state import OutfitEntry
    from create_char_passport.wizard.outfits import current_outfit_index

    state = blank_state("Conan")
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="1", prompt="cloak")]
    state.props_enabled = True
    state.props = [PropEntry(id="1", name="sword", shots=[PropShot()])]
    save_state(state)
    session = WizardSession(current_screen=ScreenId.PROPS, character=state)
    handlers.on_enter_props(session)  # cursor → prop_1_shot_1
    handlers.on_props_back(session)  # leaves first prop → OUTFITS
    assert session.current_screen is ScreenId.OUTFITS
    handlers.on_enter_outfits(session)  # the back chain runs this next
    assert current_outfit_index(state) is not None  # usable outfit cursor


def test_render_props_components_and_slot() -> None:
    import gradio as gr

    with gr.Blocks():
        handle = render_props()
    assert handle.ai_check is not None
    assert handle.ai_edit is None
    assert handle.ai_check.context.step_key == "prop_shot_step"
    for key in PROPS_REFRESH_KEYS:
        assert key in handle.components
    # Every per-shot K4 ai-check container is reachable (not just the first).
    for j in range(3):
        assert f"shot_ai_check_{j}" in handle.components
