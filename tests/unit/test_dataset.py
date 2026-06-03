"""Tests for the dataset-phase wizard logic (HLE-730)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.state import StepRecord, blank_state
from create_char_passport.storage import APPROVED_DIR, REJECTED_DIR, character_dir, save_state
from create_char_passport.wizard import dataset, generation


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


class _Capture:
    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        prompt_layers,
        refs,
        outfit_conflict=False,
        *,
        output_path,
        model=None,
        meter=None,
        aspect_ratio=None,
    ):
        self.calls.append(
            {
                "layers": dict(prompt_layers),
                "roles": [r.role for r in refs],
                "outfit_conflict": outfit_conflict,
            }
        )
        if not self.ok:
            return GenerationResult(image_path=None, ok=False, error="boom — retry")
        Path(output_path).write_bytes(b"img")
        if meter is not None:
            meter.image_usd += 0.05
            meter.image_calls += 1
        return GenerationResult(image_path=str(output_path), ok=True)


def _ready(state) -> None:
    """Approve passport face+body + style ref so identity_refs is complete."""
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


def _with_compositions(state, items: list[str]) -> None:
    state.dataset_compositions = list(items)


# --------------------------------------------------------------------------- #
# Compositions
# --------------------------------------------------------------------------- #
def test_ensure_compositions_seeds_defaults(bucket: Path) -> None:
    state = blank_state("Conan")
    assert state.dataset_compositions == []
    dataset.ensure_compositions(state)
    assert state.dataset_compositions == list(dataset.DEFAULT_DATASET_COMPOSITIONS)
    # Idempotent — does not duplicate or reset existing edits.
    state.dataset_compositions = ["custom"]
    dataset.ensure_compositions(state)
    assert state.dataset_compositions == ["custom"]


def test_dataset_name_slug(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_compositions(state, ["full body, walking pose"])
    assert dataset.dataset_name(state, 0) == "full_body_walking_pose"


def test_add_and_edit_composition(bucket: Path) -> None:
    state = blank_state("Conan")
    assert dataset.add_composition(state, "  sitting  ") == 0
    assert state.dataset_compositions == ["sitting"]
    assert dataset.add_composition(state, "   ") == 0  # blank ignored, list unchanged
    assert state.dataset_compositions == ["sitting"]
    dataset.edit_composition(state, 0, "  kneeling  ")
    assert state.dataset_compositions[0] == "kneeling"


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def test_generate_frame_composition_outfit_and_refs(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["full body, walking pose"])
    fake = _Capture()
    monkeypatch.setattr(generation, "generate_image", fake)
    result = dataset.generate_dataset_frame(state, 0)
    assert result.ok
    # Working file is keyed by the STABLE dataset_<idx>, not the editable slug.
    assert state.steps["dataset_0"].last_path == "refs/dataset_0.png"
    call = fake.calls[0]
    assert call["roles"] == ["style", "face", "body"]  # identity refs
    assert "walking pose" in call["layers"]["composition"]
    assert "neutral grey background" in call["layers"]["composition"]
    assert call["outfit_conflict"] is False  # base outfit active


def test_generate_frame_outfit_conflict_when_non_base_active(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["sitting"])
    state.active_outfit_id = "1"  # a non-base outfit is active
    fake = _Capture()
    monkeypatch.setattr(generation, "generate_image", fake)
    dataset.generate_dataset_frame(state, 0)
    assert fake.calls[0]["outfit_conflict"] is True


def test_regenerate_archives_previous(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    dataset.generate_dataset_frame(state, 0)
    dataset.generate_dataset_frame(state, 0)  # regen
    rejected = character_dir(state.character_id) / REJECTED_DIR
    # Archived under the stable slot key, exactly one frame per single regen.
    assert [p.name for p in rejected.glob("dataset_0_attempt*.png")] == ["dataset_0_attempt1.png"]


def test_edit_then_regenerate_archives_prior(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Editing the composition then regenerating still archives the prior frame
    # (working file is slot-stable, so the regen archive always fires).
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    dataset.generate_dataset_frame(state, 0)
    dataset.edit_composition(state, 0, "running")
    dataset.generate_dataset_frame(state, 0)  # regen after edit
    cdir = character_dir(state.character_id)
    assert list((cdir / REJECTED_DIR).glob("dataset_0_attempt*.png"))  # prior frame archived
    assert state.steps["dataset_0"].last_path == "refs/dataset_0.png"  # stable, no orphan


def test_duplicate_compositions_get_distinct_files(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two compositions that slugify the same must not overwrite each other.
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking", "walking"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    for i in range(2):
        dataset.generate_dataset_frame(state, i)
        dataset.approve_dataset_frame(state, i)
    # Distinct working files (slot-keyed) and distinct approved files (deduped).
    assert state.steps["dataset_0"].last_path != state.steps["dataset_1"].last_path
    assert state.steps["dataset_0"].approved_path != state.steps["dataset_1"].approved_path
    approved = character_dir(state.character_id) / APPROVED_DIR
    assert len(list(approved.glob("*.png"))) == 2  # one artifact per frame, no overwrite
    assert len(dataset.approved_samples(state)) == 2


def test_reapprove_is_idempotent(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    dataset.generate_dataset_frame(state, 0)
    assert dataset.approve_dataset_frame(state, 0) is True
    first = state.steps["dataset_0"].approved_path
    assert dataset.approve_dataset_frame(state, 0) is True  # re-approve
    assert state.steps["dataset_0"].approved_path == first  # same file, no duplicate
    approved = character_dir(state.character_id) / APPROVED_DIR
    assert len(list(approved.glob("*.png"))) == 1


def test_generate_frame_failure_no_step(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking"])
    monkeypatch.setattr(generation, "generate_image", _Capture(ok=False))
    result = dataset.generate_dataset_frame(state, 0)
    assert not result.ok
    assert "dataset_0" not in state.steps


def test_generate_frame_bad_index_raises(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_compositions(state, ["walking"])
    with pytest.raises(IndexError, match="out of range"):
        dataset.generate_dataset_frame(state, 5)


# --------------------------------------------------------------------------- #
# Approve → archive
# --------------------------------------------------------------------------- #
def test_approve_copies_to_approved(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["full body, walking pose"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    dataset.generate_dataset_frame(state, 0)
    assert dataset.approve_dataset_frame(state, 0) is True
    approved = character_dir(state.character_id) / APPROVED_DIR / "full_body_walking_pose.png"
    assert approved.is_file()  # named by composition
    assert state.steps["dataset_0"].approved_path == "approved/full_body_walking_pose.png"
    assert dataset.frame_approved(state, 0) is True
    # The working frame stays as the preview (copy, not move).
    assert dataset.frame_generated(state, 0) is True


def test_approve_without_generation_is_noop(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    _with_compositions(state, ["walking"])
    assert dataset.approve_dataset_frame(state, 0) is False
    assert dataset.frame_approved(state, 0) is False


# --------------------------------------------------------------------------- #
# Completion + archive + cursor
# --------------------------------------------------------------------------- #
def test_all_approved_and_samples(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_compositions(state, ["walking", "sitting"])
    monkeypatch.setattr(generation, "generate_image", _Capture())
    assert dataset.all_dataset_approved(state) is False
    for i in range(2):
        dataset.generate_dataset_frame(state, i)
        dataset.approve_dataset_frame(state, i)
    assert dataset.all_dataset_approved(state) is True
    assert len(dataset.approved_samples(state)) == 2


def test_all_approved_false_when_empty(bucket: Path) -> None:
    assert dataset.all_dataset_approved(blank_state("Conan")) is False


def test_cursor_helpers(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_compositions(state, ["a", "b"])
    assert dataset.first_dataset_step(state) == "dataset_0"
    assert dataset.current_dataset_index(state) is None
    state.current_step = "dataset_1"
    assert dataset.current_dataset_index(state) == 1
    assert dataset.adjacent_dataset_step(state, 1, forward=True) is None
    assert dataset.adjacent_dataset_step(state, 0, forward=True) == "dataset_1"
    assert dataset.adjacent_dataset_step(state, 1, forward=False) == "dataset_0"


def test_first_dataset_step_empty(bucket: Path) -> None:
    assert dataset.first_dataset_step(blank_state("Conan")) is None
