"""Tests for the dataset screen — session handlers + refresh glue (HLE-730)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.screens.views import (
    DATASET_REFRESH_KEYS,
    FINISH_REFRESH_KEYS,
    dataset_refresh,
    finish_refresh,
    render_dataset,
    render_finish,
)
from create_char_passport.state import CharacterState, StepRecord, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import dataset, generation


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


def _started(
    bucket: Path, *, compositions: list[str] | None = None
) -> tuple[WizardSession, CharacterState]:
    state = blank_state("Conan")
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"
    if compositions is not None:
        state.dataset_compositions = list(compositions)
    save_state(state)
    session = WizardSession(current_screen=ScreenId.DATASET, character=state)
    handlers.on_enter_dataset(session)
    return session, state


# --------------------------------------------------------------------------- #
# Enter / guards
# --------------------------------------------------------------------------- #
def test_on_enter_dataset_seeds_compositions_and_cursor(bucket: Path) -> None:
    _session, char = _started(bucket)  # no compositions → defaults seeded
    assert char.dataset_compositions == list(dataset.DEFAULT_DATASET_COMPOSITIONS)
    assert char.current_step == "dataset_0"


def test_on_enter_dataset_preserves_resumed_cursor(bucket: Path) -> None:
    session, char = _started(bucket, compositions=["a", "b"])
    char.current_step = "dataset_1"
    handlers.on_enter_dataset(session)
    assert char.current_step == "dataset_1"


def test_dataset_handlers_noop_without_character() -> None:
    session = WizardSession(current_screen=ScreenId.DATASET)
    assert handlers.on_enter_dataset(session).character is None
    assert handlers.on_dataset_generate(session).character is None
    assert handlers.on_dataset_approve(session).character is None
    assert handlers.on_dataset_back(session).current_screen is not ScreenId.DATASET


def test_on_enter_dataset_noop_off_screen(bucket: Path) -> None:
    # Chained into every forward transition — must NOT seed/clobber when the
    # destination is a different screen (the second guard arm).
    session, char = _started(bucket, compositions=[])
    char.dataset_compositions = []
    char.current_step = "prop_1_shot_1"
    session.current_screen = ScreenId.PROPS
    handlers.on_enter_dataset(session)
    assert char.current_step == "prop_1_shot_1"  # cursor preserved
    assert char.dataset_compositions == []  # not seeded


# --------------------------------------------------------------------------- #
# Generate / edit / add
# --------------------------------------------------------------------------- #
def test_on_dataset_generate_sets_ref_and_bills(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket, compositions=["walking"])
    out = handlers.on_dataset_generate(session)
    assert char.steps["dataset_0"].last_path == "refs/dataset_0.png"  # slot-stable key
    assert out.cost.image_calls == 1
    assert char.cost.image_calls == 1


def test_on_dataset_generate_failure_no_bill(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_fail)
    session, char = _started(bucket, compositions=["walking"])
    out = handlers.on_dataset_generate(session)
    assert "dataset_0" not in char.steps
    assert out.cost.image_calls == 0


def test_on_dataset_prompt_edit_persists(bucket: Path) -> None:
    session, char = _started(bucket, compositions=["walking"])
    handlers.on_dataset_prompt_edit(session, "  sitting on a stool  ")
    assert char.dataset_compositions[0] == "sitting on a stool"


def test_on_dataset_add_composition(bucket: Path) -> None:
    session, char = _started(bucket, compositions=["walking"])
    handlers.on_dataset_add_composition(session, "  crouching  ")
    assert char.dataset_compositions == ["walking", "crouching"]
    handlers.on_dataset_add_composition(session, "   ")  # blank ignored
    assert char.dataset_compositions == ["walking", "crouching"]


# --------------------------------------------------------------------------- #
# Approve → next / finish
# --------------------------------------------------------------------------- #
def test_approve_without_generation_notices(bucket: Path) -> None:
    session, _char = _started(bucket, compositions=["walking"])
    out = handlers.on_dataset_approve(session)
    assert out.current_screen is ScreenId.DATASET
    assert "Сначала сгенерируй" in out.notice


def test_approve_advances_then_finishes(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, char = _started(bucket, compositions=["walking", "sitting"])
    handlers.on_dataset_generate(session)
    out = handlers.on_dataset_approve(session)
    assert out.current_screen is ScreenId.DATASET  # stays — next composition
    assert char.current_step == "dataset_1"
    handlers.on_dataset_generate(session)
    out = handlers.on_dataset_approve(session)
    assert out.current_screen is ScreenId.FINISH  # array done → finish
    assert char.current_step is None  # wizard complete (§6)


def test_back_steps_between_then_out(bucket: Path) -> None:
    session, char = _started(bucket, compositions=["a", "b"])
    char.current_step = "dataset_1"
    handlers.on_dataset_back(session)
    assert char.current_step == "dataset_0"
    out = handlers.on_dataset_back(session)
    assert out.current_screen is not ScreenId.DATASET


# --------------------------------------------------------------------------- #
# Refresh glue
# --------------------------------------------------------------------------- #
def test_dataset_refresh_none_is_all_noop() -> None:
    updates = dataset_refresh(WizardSession())
    assert len(updates) == len(DATASET_REFRESH_KEYS)


def test_dataset_refresh_populates(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, _char = _started(bucket, compositions=["walking", "sitting"])
    upd = dict(zip(DATASET_REFRESH_KEYS, dataset_refresh(session), strict=True))
    assert "кадр 1 из 2" in upd["dataset_progress"]["value"]
    assert upd["composition_prompt"]["value"] == "walking"
    assert upd["approve_btn"]["interactive"] is False  # not generated yet
    handlers.on_dataset_generate(session)
    upd = dict(zip(DATASET_REFRESH_KEYS, dataset_refresh(session), strict=True))
    assert upd["approve_btn"]["interactive"] is True
    assert upd["dataset_preview"]["value"] is not None


def test_dataset_refresh_missing_file_no_preview(bucket: Path) -> None:
    # last_path recorded but the file is gone (e.g. stale state on an ephemeral
    # filesystem) → the is_file() guard collapses the preview to None.
    session, char = _started(bucket, compositions=["walking"])
    char.steps["dataset_0"] = StepRecord(last_path="refs/dataset_0.png")  # no file on disk
    upd = dict(zip(DATASET_REFRESH_KEYS, dataset_refresh(session), strict=True))
    assert upd["dataset_preview"]["value"] is None


def test_finish_refresh_shows_samples(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    session, _char = _started(bucket, compositions=["walking"])
    handlers.on_dataset_generate(session)
    handlers.on_dataset_approve(session)  # → approved/ + finish
    upd = dict(zip(FINISH_REFRESH_KEYS, finish_refresh(session), strict=True))
    assert "1" in upd["finish_note"]["value"]
    assert len(upd["finish_gallery"]["value"]) == 1


def test_render_dataset_and_finish_components() -> None:
    import gradio as gr

    with gr.Blocks():
        ds = render_dataset()
        fn = render_finish()
    assert ds.ai_check is not None
    assert ds.ai_edit is not None  # dataset has both K4 slots
    assert ds.ai_check.context.step_key == "dataset_step"
    for key in DATASET_REFRESH_KEYS:
        assert key in ds.components
    for key in FINISH_REFRESH_KEYS:
        assert key in fn.components
    # LoRA-ready export controls (HLE-805) live on the finish screen.
    for key in ("export_btn", "export_file", "export_note"):
        assert key in fn.components
