"""Tests for the outfits screen — session handlers + the refresh glue."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult, SceneId
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.screens.views import (
    OUTFITS_REFRESH_KEYS,
    outfits_refresh,
    render_outfits,
)
from create_char_passport.state import CharacterState, OutfitDetail, OutfitEntry, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import generation


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def _fake_ok(
    prompt_layers,
    refs,
    outfit_conflict=False,
    *,
    output_path,
    model=None,
    meter=None,
    aspect_ratio=None,
):
    Path(output_path).write_bytes(b"img")
    if meter is not None:
        meter.image_usd += 0.05
        meter.image_calls += 1
    return GenerationResult(image_path=str(output_path), ok=True)


def _fake_fail(
    prompt_layers,
    refs,
    outfit_conflict=False,
    *,
    output_path,
    model=None,
    meter=None,
    aspect_ratio=None,
):
    return GenerationResult(image_path=None, ok=False, error="boom — retry")


def _started(
    bucket: Path, *, complex_: bool = False, n: int = 1
) -> tuple[WizardSession, CharacterState]:
    state = blank_state("Conan")
    state.outfits_enabled = True
    state.outfits = [
        OutfitEntry(id=str(i + 1), prompt=f"outfit {i + 1}", complex=complex_) for i in range(n)
    ]
    save_state(state)
    session = WizardSession(current_screen=ScreenId.OUTFITS, character=state)
    handlers.on_enter_outfits(session)  # seed the cursor on the first outfit
    return session, state


# --------------------------------------------------------------------------- #
# Enter / guards
# --------------------------------------------------------------------------- #
def test_on_enter_outfits_seeds_first(bucket: Path) -> None:
    _session, char = _started(bucket, n=2)
    assert char.current_step == "outfit_1"


def test_on_enter_outfits_preserves_resumed_cursor(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    char.current_step = "outfit_2"
    handlers.on_enter_outfits(session)  # already on an outfit → keep it
    assert char.current_step == "outfit_2"


def test_outfit_handlers_noop_without_character() -> None:
    session = WizardSession(current_screen=ScreenId.OUTFITS)
    assert handlers.on_enter_outfits(session).character is None
    assert handlers.on_outfit_scene_generate(session, SceneId.FRONT_FULL).character is None
    assert handlers.on_approve_outfit(session).character is None
    assert handlers.on_outfit_add_detail(session).character is None
    assert handlers.on_outfit_prompt_edit(session, "x").character is None
    assert handlers.on_toggle_outfit_complex(session, True).character is None
    assert handlers.on_outfit_detail_generate(session, 0).character is None
    # Back with no character just leaves the phase without crashing.
    assert handlers.on_outfits_back(session).current_screen is not ScreenId.OUTFITS


def test_detail_generate_bad_index_noop(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, _char = _started(bucket, complex_=True)
    out = handlers.on_outfit_detail_generate(session, 5)  # no such detail cell
    assert out.cost.image_calls == 0


# --------------------------------------------------------------------------- #
# Generate / approve flags
# --------------------------------------------------------------------------- #
def test_on_outfit_scene_generate_sets_ref_and_bills(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    out = handlers.on_outfit_scene_generate(session, SceneId.FRONT_FULL)
    assert char.outfits[0].refs.front_full == "refs/outfit_1_front_full.png"
    assert out.cost.image_calls == 1
    assert char.cost.image_calls == 1


def test_on_outfit_scene_generate_failure_no_bill(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    session, char = _started(bucket)
    out = handlers.on_outfit_scene_generate(session, SceneId.FRONT_FULL)
    assert char.outfits[0].refs.front_full is None
    assert out.cost.image_calls == 0
    assert "boom" in out.notice


def test_on_outfit_scene_approve_toggle(bucket: Path) -> None:
    session, char = _started(bucket)
    handlers.on_outfit_scene_approve_toggle(session, SceneId.FRONT_FULL, True)
    assert char.outfits[0].refs.front_full_approved is True
    handlers.on_outfit_scene_approve_toggle(session, SceneId.FRONT_FULL, False)
    assert char.outfits[0].refs.front_full_approved is False


def test_on_toggle_complex(bucket: Path) -> None:
    session, char = _started(bucket)
    handlers.on_toggle_outfit_complex(session, True)
    assert char.outfits[0].complex is True


def test_on_outfit_prompt_edit(bucket: Path) -> None:
    session, char = _started(bucket)
    handlers.on_outfit_prompt_edit(session, "  blue tunic  ")
    assert char.outfits[0].prompt == "blue tunic"


# --------------------------------------------------------------------------- #
# Details
# --------------------------------------------------------------------------- #
def test_detail_add_generate_delete_flow(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket, complex_=True)
    handlers.on_outfit_scene_generate(session, SceneId.FRONT_FULL)  # detail needs the front ref
    handlers.on_outfit_add_detail(session)
    assert len(char.outfits[0].details) == 1
    out = handlers.on_outfit_detail_generate(session, 0)
    assert char.outfits[0].details[0].ref == "refs/outfit_1_detail_1.png"
    assert out.cost.image_calls == 2  # front + detail
    # delete a generated detail → first asks to confirm (no removal yet).
    handlers.on_outfit_delete_detail(session, 0)
    assert session.outfit_pending_delete == (0, 1)
    assert len(char.outfits[0].details) == 1
    handlers.on_outfit_delete_detail_confirmed(session, 0)
    assert len(char.outfits[0].details) == 0
    assert session.outfit_pending_delete is None


def test_delete_ungenerated_detail_is_immediate(bucket: Path) -> None:
    session, char = _started(bucket, complex_=True)
    handlers.on_outfit_add_detail(session)
    handlers.on_outfit_delete_detail(session, 0)  # no generation → removed at once
    assert len(char.outfits[0].details) == 0
    assert session.outfit_pending_delete is None


def test_detail_prompt_edit_persists(bucket: Path) -> None:
    session, char = _started(bucket, complex_=True)
    handlers.on_outfit_add_detail(session)
    handlers.on_outfit_detail_prompt_edit(session, "  ornate buckle  ", j=0)
    assert char.outfits[0].details[0].prompt == "ornate buckle"


def test_stale_delete_confirm_cleared_by_other_action(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, _char = _started(bucket, complex_=True)
    handlers.on_outfit_scene_generate(session, SceneId.FRONT_FULL)
    handlers.on_outfit_add_detail(session)
    handlers.on_outfit_detail_generate(session, 0)
    handlers.on_outfit_delete_detail(session, 0)  # arm the confirm
    assert session.outfit_pending_delete == (0, 1)
    handlers.on_toggle_outfit_complex(session, True)  # unrelated action dismisses it
    assert session.outfit_pending_delete is None


def test_approve_pending_detail_soft_confirm(bucket: Path) -> None:
    session, char = _started(bucket)
    char.outfits[0].complex = True
    char.outfits[0].refs.front_full = "a.png"
    char.outfits[0].refs.back_full = "b.png"
    char.outfits[0].refs.profile_full = "c.png"
    char.outfits[0].details = [OutfitDetail(prompt="buckle")]
    # First Approve: a filled-but-ungenerated detail → soft confirm, stays put.
    out = handlers.on_approve_outfit(session)
    assert out.current_screen is ScreenId.OUTFITS
    assert session.outfit_pending_approve_confirm is True
    assert "без генерации" in out.notice
    # Second Approve: proceeds (details persist, nothing deleted).
    out = handlers.on_approve_outfit(session)
    assert char.active_outfit_id == "1"
    assert char.outfits[0].details[0].prompt == "buckle"  # not discarded


# --------------------------------------------------------------------------- #
# Approve / back navigation
# --------------------------------------------------------------------------- #
def test_approve_incomplete_stays_and_notices(bucket: Path) -> None:
    session, _char = _started(bucket)
    out = handlers.on_approve_outfit(session)
    assert out.current_screen is ScreenId.OUTFITS
    assert "обязательные сцены" in out.notice


def test_approve_advances_to_next_outfit(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    char.outfits[0].refs.front_full = "a.png"
    char.outfits[0].refs.back_full = "b.png"
    out = handlers.on_approve_outfit(session)
    assert out.current_screen is ScreenId.OUTFITS  # stays in phase
    assert char.current_step == "outfit_2"  # advanced to next outfit
    assert char.outfits[0].refs.front_full_approved is True


def test_approve_last_outfit_leaves_phase(bucket: Path) -> None:
    session, char = _started(bucket, n=1)
    char.outfits[0].refs.front_full = "a.png"
    char.outfits[0].refs.back_full = "b.png"
    out = handlers.on_approve_outfit(session)
    assert out.current_screen is ScreenId.DATASET  # no props/emotions → dataset next
    assert char.active_outfit_id == "1"


def test_back_steps_between_outfits_then_out(bucket: Path) -> None:
    session, char = _started(bucket, n=2)
    char.current_step = "outfit_2"
    out = handlers.on_outfits_back(session)
    assert char.current_step == "outfit_1"  # back to previous outfit
    assert out.current_screen is ScreenId.OUTFITS
    out = handlers.on_outfits_back(session)
    assert out.current_screen is not ScreenId.OUTFITS  # left the phase


# --------------------------------------------------------------------------- #
# Refresh glue
# --------------------------------------------------------------------------- #
def test_outfits_refresh_none_is_all_noop() -> None:
    updates = outfits_refresh(WizardSession())
    assert len(updates) == len(OUTFITS_REFRESH_KEYS)


def test_outfits_refresh_populates_and_hides_profile_when_simple(bucket: Path) -> None:
    session, char = _started(bucket)
    cdir = character_dir(char.character_id)
    (cdir / "refs/outfit_1_front_full.png").write_bytes(b"img")
    char.outfits[0].refs.front_full = "refs/outfit_1_front_full.png"
    upd = dict(zip(OUTFITS_REFRESH_KEYS, outfits_refresh(session), strict=True))
    assert "outfit 1" in upd["outfit_label"]["value"]
    assert upd["front_full_preview"]["value"] == str(cdir / "refs/outfit_1_front_full.png")
    assert upd["front_full_block"]["visible"] is True
    assert upd["profile_full_block"]["visible"] is False  # simple → hidden
    assert upd["detail_block"]["visible"] is False
    assert upd["approve_btn"]["interactive"] is False  # back not generated yet


def test_outfits_refresh_complex_shows_profile_and_details(bucket: Path) -> None:
    session, _char = _started(bucket, complex_=True)
    handlers.on_outfit_add_detail(session)
    upd = dict(zip(OUTFITS_REFRESH_KEYS, outfits_refresh(session), strict=True))
    assert upd["profile_full_block"]["visible"] is True
    assert upd["detail_block"]["visible"] is True
    assert upd["detail_cell_0"]["visible"] is True
    assert upd["detail_cell_1"]["visible"] is False  # only one detail added


def test_outfits_refresh_approve_enabled_when_scenes_present(bucket: Path) -> None:
    session, char = _started(bucket)
    char.outfits[0].refs.front_full = "a.png"
    char.outfits[0].refs.back_full = "b.png"
    upd = dict(zip(OUTFITS_REFRESH_KEYS, outfits_refresh(session), strict=True))
    assert upd["approve_btn"]["interactive"] is True


def test_render_outfits_components_and_slot() -> None:
    import gradio as gr

    with gr.Blocks():
        handle = render_outfits()
    assert handle.ai_check is not None
    assert handle.ai_edit is None
    assert handle.ai_check.context.step_key == "outfit_step"
    for key in OUTFITS_REFRESH_KEYS:
        assert key in handle.components
