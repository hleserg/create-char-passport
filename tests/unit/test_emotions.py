"""Tests for the emotions-phase logic + the shared generation helpers."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.state import StepRecord, blank_state
from create_char_passport.storage import REJECTED_DIR, character_dir, save_state
from create_char_passport.wizard import emotions, generation


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


def _passport_done(state) -> None:
    """Approve passport face + body and set a style ref so identity is complete."""
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


# --------------------------------------------------------------------------- #
# generation: identity refs
# --------------------------------------------------------------------------- #
def test_identity_refs_style_face_body_order(bucket: Path) -> None:
    state = blank_state("Heron")
    save_state(state)
    _passport_done(state)
    assert [r.role for r in generation.identity_refs(state)] == ["style", "face", "body"]


def test_identity_refs_skips_missing(bucket: Path) -> None:
    state = blank_state("Heron")
    save_state(state)
    assert generation.identity_refs(state) == []  # nothing approved, no style
    state.style_ref = "refs/style.png"  # recorded but file absent
    assert generation.identity_refs(state) == []


# --------------------------------------------------------------------------- #
# generation: render_step_image
# --------------------------------------------------------------------------- #
def test_render_step_image_success_then_archive(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    cdir = character_dir(state.character_id)
    result, relative = generation.render_step_image(state, "emotion_neutral", {"style": "x"}, [])
    assert result.ok
    assert relative == "refs/emotion_neutral.png"
    assert (cdir / "refs/emotion_neutral.png").is_file()
    # A second render archives the previous frame to rejected/ (never overwrites, §5).
    generation.render_step_image(state, "emotion_neutral", {"style": "x"}, [])
    assert list((cdir / REJECTED_DIR).glob("emotion_neutral_attempt*.png"))


def test_render_step_image_failure_preserves(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    result, relative = generation.render_step_image(state, "emotion_neutral", {"style": "x"}, [])
    assert not result.ok
    assert relative is None
    cdir = character_dir(state.character_id)
    assert not (cdir / "refs/emotion_neutral.png").exists()
    assert not (cdir / "refs/emotion_neutral.png.pending").exists()  # no leftover pending


# --------------------------------------------------------------------------- #
# emotions: generate / missing
# --------------------------------------------------------------------------- #
def test_emotion_values(bucket: Path) -> None:
    # "neutral" is intentionally absent — the passport already covers it.
    assert emotions.emotion_values(blank_state("Heron")) == [
        "angry, furious",
        "smiling warmly",
    ]


def test_generate_emotion_sets_ref(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Heron")
    save_state(state)
    _passport_done(state)
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    result = emotions.generate_emotion(state, 0)
    assert result.ok
    assert state.emotions.items[0].ref == "refs/emotion_angry_furious.png"


def test_generate_emotion_failure_leaves_no_ref(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    _passport_done(state)
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    result = emotions.generate_emotion(state, 1)
    assert not result.ok
    assert state.emotions.items[1].ref is None


def test_generate_emotion_index_out_of_range() -> None:
    with pytest.raises(IndexError, match="out of range"):
        emotions.generate_emotion(blank_state("Heron"), 99)


def test_generate_base_emotion_sets_ref(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Heron")
    save_state(state)
    _passport_done(state)
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "grim, brooding"
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    result = emotions.generate_base_emotion(state)
    assert result.ok
    assert state.emotions.base_emotion.ref == "refs/base_emotion.png"


def test_missing_emotion_refs(bucket: Path) -> None:
    state = blank_state("Heron")
    state.emotions.enabled = True  # series counts only when the block is on
    assert emotions.missing_emotion_refs(state) == ["angry, furious", "smiling warmly"]
    for item in state.emotions.items:
        item.ref = "refs/x.png"
    assert emotions.missing_emotion_refs(state) == []
    state.emotions.base_emotion.enabled = True  # enabled but ungenerated → listed
    assert emotions.missing_emotion_refs(state) == ["базовая эмоция"]


def test_missing_emotion_refs_base_only(bucket: Path) -> None:
    """Series off + base on: only the base emotion is required (not the defaults)."""
    state = blank_state("Heron")  # emotions.enabled is False by default
    state.emotions.base_emotion.enabled = True
    assert emotions.missing_emotion_refs(state) == ["базовая эмоция"]
    state.emotions.base_emotion.ref = "refs/base_emotion.png"
    assert emotions.missing_emotion_refs(state) == []
