"""Tests for the emotions screen — session handlers + the refresh glue."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.screens.views import (
    EMOTIONS_REFRESH_KEYS,
    emotions_refresh,
    render_emotions,
)
from create_char_passport.state import CharacterState, blank_state
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


def _started(bucket: Path) -> tuple[WizardSession, CharacterState]:
    state = blank_state("Heron")
    save_state(state)
    return WizardSession(current_screen=ScreenId.EMOTIONS, character=state), state


# --------------------------------------------------------------------------- #
# Enter / guards
# --------------------------------------------------------------------------- #
def test_on_enter_emotions_marks_phase(bucket: Path) -> None:
    session, char = _started(bucket)
    char.emotions.enabled = True
    session.emotions_offer_skip = True
    handlers.on_enter_emotions(session)
    assert char.current_step == "emotion_neutral"  # resume routes here
    assert session.emotions_offer_skip is False


def test_on_enter_emotions_base_only_targets_base_step(bucket: Path) -> None:
    """Series off → resume marker is the base-emotion step (the only in-pipeline one)."""
    session, char = _started(bucket)
    char.emotions.enabled = False
    char.emotions.base_emotion.enabled = True
    handlers.on_enter_emotions(session)
    assert char.current_step == "base_emotion"


def test_on_enter_emotions_noop_off_screen(bucket: Path) -> None:
    session, char = _started(bucket)
    session.current_screen = ScreenId.PASSPORT
    char.current_step = None
    handlers.on_enter_emotions(session)
    assert char.current_step is None


def test_emotions_handlers_noop_without_character() -> None:
    session = WizardSession(current_screen=ScreenId.EMOTIONS)
    assert handlers.on_enter_emotions(session).character is None
    assert handlers.on_emotion_generate(session, 0).character is None
    assert handlers.on_base_emotion_generate(session).character is None
    assert handlers.on_emotions_approve(session).character is None
    assert handlers.on_emotions_skip(session).character is None


# --------------------------------------------------------------------------- #
# Generate
# --------------------------------------------------------------------------- #
def test_on_emotion_generate_sets_ref_and_bills(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    out = handlers.on_emotion_generate(session, 0)
    assert char.emotions.items[0].ref == "refs/emotion_neutral.png"
    assert out.cost.image_calls == 1
    assert char.cost.image_calls == 1
    assert "neutral" in out.notice


def test_on_emotion_generate_bad_index_is_noop(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, _char = _started(bucket)
    out = handlers.on_emotion_generate(session, 99)
    assert out.cost.image_calls == 0  # nothing generated


def test_on_base_emotion_generate_requires_enabled(bucket: Path) -> None:
    session, char = _started(bucket)
    char.emotions.base_emotion.enabled = False
    out = handlers.on_base_emotion_generate(session)
    assert "Включи базовую эмоцию" in out.notice
    assert char.emotions.base_emotion.ref is None


def test_on_base_emotion_generate_requires_value(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Enabled but blank value would resolve EXPRESSION to neutral — must be refused.
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    char.emotions.base_emotion.enabled = True
    char.emotions.base_emotion.value = "   "
    out = handlers.on_base_emotion_generate(session)
    assert "Введи выражение" in out.notice
    assert char.emotions.base_emotion.ref is None
    assert out.cost.image_calls == 0  # nothing generated


def test_on_emotion_generate_failure_no_ref_no_bill(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    session, char = _started(bucket)
    char.emotions.enabled = True
    out = handlers.on_emotion_generate(session, 0)
    assert char.emotions.items[0].ref is None
    assert out.cost.image_calls == 0  # a failed call bills nothing
    assert char.cost.image_calls == 0
    assert "boom" in out.notice


def test_on_base_emotion_generate_failure_no_ref_no_bill(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    session, char = _started(bucket)
    char.emotions.base_emotion.enabled = True
    char.emotions.base_emotion.value = "grim, brooding"
    out = handlers.on_base_emotion_generate(session)
    assert char.emotions.base_emotion.ref is None
    assert out.cost.image_calls == 0
    assert "boom" in out.notice


def test_on_base_emotion_generate_success(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    char.emotions.base_emotion.enabled = True
    char.emotions.base_emotion.value = "grim, brooding"
    out = handlers.on_base_emotion_generate(session)
    assert char.emotions.base_emotion.ref == "refs/base_emotion.png"
    assert out.cost.image_calls == 1


# --------------------------------------------------------------------------- #
# Approve / skip / back
# --------------------------------------------------------------------------- #
def test_on_emotions_approve_incomplete_offers_skip(bucket: Path) -> None:
    session, char = _started(bucket)
    char.emotions.enabled = True  # ungenerated series → skip offer
    out = handlers.on_emotions_approve(session)
    assert out.current_screen is ScreenId.EMOTIONS  # stays
    assert out.emotions_offer_skip is True
    assert "Не сгенерированы" in out.notice


def test_on_emotions_approve_complete_advances(bucket: Path) -> None:
    session, char = _started(bucket)
    char.emotions.enabled = True
    for item in char.emotions.items:
        item.ref = "refs/x.png"
    out = handlers.on_emotions_approve(session)
    # No outfits/props enabled → next phase after emotions is the dataset.
    assert out.current_screen is ScreenId.DATASET
    assert out.emotions_offer_skip is False


def test_on_emotions_approve_base_only_completes(bucket: Path) -> None:
    """Series off + base generated → Approve advances (no phantom series gate)."""
    session, char = _started(bucket)
    char.emotions.enabled = False
    char.emotions.base_emotion.enabled = True
    char.emotions.base_emotion.ref = "refs/base_emotion.png"
    out = handlers.on_emotions_approve(session)
    assert out.current_screen is ScreenId.DATASET
    assert out.emotions_offer_skip is False


def test_on_emotion_generate_clears_stale_skip_offer(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Generating the last missing emotion drops the lingering skip button."""
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket)
    char.emotions.enabled = True
    char.emotions.items[1].ref = "refs/x.png"
    char.emotions.items[2].ref = "refs/x.png"
    session.emotions_offer_skip = True  # Approve previously found a gap
    out = handlers.on_emotion_generate(session, 0)  # fill the last gap
    assert char.emotions.items[0].ref == "refs/emotion_neutral.png"
    assert out.emotions_offer_skip is False


def test_on_emotions_skip_advances(bucket: Path) -> None:
    session, _char = _started(bucket)
    session.emotions_offer_skip = True
    out = handlers.on_emotions_skip(session)
    assert out.current_screen is ScreenId.DATASET
    assert out.emotions_offer_skip is False


def test_on_emotions_back_to_passport(bucket: Path) -> None:
    session, _char = _started(bucket)
    out = handlers.on_emotions_back(session)
    assert out.current_screen is ScreenId.PASSPORT


# --------------------------------------------------------------------------- #
# Refresh glue
# --------------------------------------------------------------------------- #
def test_emotions_refresh_none_is_all_noop() -> None:
    updates = emotions_refresh(WizardSession())
    assert len(updates) == len(EMOTIONS_REFRESH_KEYS)
    assert all(upd == {"__type__": "update"} for upd in updates)


def test_emotions_refresh_populates(bucket: Path) -> None:
    session, char = _started(bucket)
    cdir = character_dir(char.character_id)
    (cdir / "refs/emotion_neutral.png").write_bytes(b"img")
    char.emotions.enabled = True
    char.emotions.items[0].ref = "refs/emotion_neutral.png"
    char.emotions.base_emotion.enabled = True
    session.emotions_offer_skip = True
    upd = dict(zip(EMOTIONS_REFRESH_KEYS, emotions_refresh(session), strict=True))
    assert upd["emotion_row"]["visible"] is True
    assert "neutral" in upd["emo_label_0"]["value"]
    assert upd["emo_preview_0"]["value"] == str(cdir / "refs/emotion_neutral.png")
    assert upd["base_emotion_enabled"]["value"] is True
    assert upd["base_emotion_block"]["visible"] is True
    assert upd["base_emotion_value"]["interactive"] is True
    assert upd["skip_btn"]["visible"] is True


def test_emotions_refresh_series_row_hidden_base_only(bucket: Path) -> None:
    """Series off → the 3-cell row is hidden and its labels blanked (no phantom cells)."""
    session, char = _started(bucket)
    char.emotions.enabled = False
    char.emotions.base_emotion.enabled = True
    upd = dict(zip(EMOTIONS_REFRESH_KEYS, emotions_refresh(session), strict=True))
    assert upd["emotion_row"]["visible"] is False
    assert upd["emo_label_0"]["value"] == ""
    assert upd["emo_preview_0"]["value"] is None


def test_emotions_refresh_dangling_ref_no_preview(bucket: Path) -> None:
    """Ref recorded but file missing (degraded resume) → preview collapses to None."""
    session, char = _started(bucket)
    char.emotions.enabled = True
    char.emotions.items[0].ref = "refs/emotion_neutral.png"  # file intentionally absent
    char.emotions.base_emotion.enabled = True
    char.emotions.base_emotion.ref = "refs/base_emotion.png"  # file intentionally absent
    upd = dict(zip(EMOTIONS_REFRESH_KEYS, emotions_refresh(session), strict=True))
    assert upd["emo_preview_0"]["value"] is None
    assert upd["base_emotion_preview"]["value"] is None


def test_emotions_refresh_base_block_hidden_when_off(bucket: Path) -> None:
    session, char = _started(bucket)
    char.emotions.base_emotion.enabled = False
    upd = dict(zip(EMOTIONS_REFRESH_KEYS, emotions_refresh(session), strict=True))
    assert upd["base_emotion_block"]["visible"] is False
    assert upd["base_emotion_value"]["interactive"] is False
    assert upd["skip_btn"]["visible"] is False


def test_render_emotions_check_slot_only_and_components() -> None:
    import gradio as gr

    with gr.Blocks():
        handle = render_emotions()
    assert handle.ai_check is not None
    assert handle.ai_edit is None
    assert handle.ai_check.context.step_key == "base_emotion"
    for key in EMOTIONS_REFRESH_KEYS:
        assert key in handle.components
