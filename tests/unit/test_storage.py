"""Tests for filesystem-backed storage."""

from __future__ import annotations

from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.state import blank_state
from create_char_passport.storage import (
    APPROVED_DIR,
    REFS_DIR,
    REJECTED_DIR,
    STATE_FILENAME,
    archive_to_rejected,
    bucket_root,
    character_dir,
    list_character_ids,
    load_state,
    next_attempt_number,
    save_state,
)


@pytest.fixture()
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    return tmp_path


def test_bucket_root_uses_settings(bucket: Path) -> None:
    root = bucket_root()
    assert root == bucket.resolve()


def test_character_dir_creates_subfolders(bucket: Path) -> None:
    folder = character_dir("heron")
    assert (folder / REFS_DIR).is_dir()
    assert (folder / APPROVED_DIR).is_dir()
    assert (folder / REJECTED_DIR).is_dir()


def test_save_and_load_state_round_trip(bucket: Path) -> None:
    state = blank_state("Heron")
    state.current_step = "passport_face"
    target = save_state(state)
    assert target.name == STATE_FILENAME
    assert target.parent.name == "heron"

    restored = load_state("heron")
    assert restored is not None
    assert restored.character_id == "heron"
    assert restored.current_step == "passport_face"


def test_load_state_missing_returns_none(bucket: Path) -> None:
    assert load_state("ghost") is None


def test_list_character_ids_filters_to_saved_states(bucket: Path) -> None:
    save_state(blank_state("Heron"))
    save_state(blank_state("Tyra"))
    # A character folder without state.json is ignored.
    (bucket / "stub" / "refs").mkdir(parents=True)
    assert list_character_ids() == ["heron", "tyra"]


def test_list_character_ids_empty_when_bucket_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "never_created"
    monkeypatch.setenv("APP_BUCKET_PATH", str(target))
    get_settings.cache_clear()
    # bucket_root() creates the dir, but we want to exercise the early return
    # path: pass an explicit root that does not exist.
    assert list_character_ids(root=tmp_path / "still_missing") == []


def test_next_attempt_number_starts_at_one(bucket: Path) -> None:
    rejected = bucket / "heron" / REJECTED_DIR
    rejected.mkdir(parents=True)
    assert next_attempt_number(rejected, "passport_face") == 1


def test_next_attempt_number_finds_first_gap(bucket: Path) -> None:
    rejected = bucket / "heron" / REJECTED_DIR
    rejected.mkdir(parents=True)
    (rejected / "passport_face_attempt1.png").write_bytes(b"x")
    (rejected / "passport_face_attempt3.png").write_bytes(b"x")
    assert next_attempt_number(rejected, "passport_face") == 2


def test_archive_to_rejected_moves_and_renames(bucket: Path) -> None:
    folder = character_dir("heron")
    frame = folder / REFS_DIR / "passport_face.png"
    frame.write_bytes(b"new-attempt")

    destination = archive_to_rejected(folder, "passport_face", frame)
    assert destination.name == "passport_face_attempt1.png"
    assert destination.exists()
    assert not frame.exists()

    # A second regeneration moves into attempt2.
    frame.write_bytes(b"second-attempt")
    destination_2 = archive_to_rejected(folder, "passport_face", frame)
    assert destination_2.name == "passport_face_attempt2.png"


def test_archive_to_rejected_no_op_when_frame_missing(bucket: Path) -> None:
    folder = character_dir("heron")
    ghost = folder / REFS_DIR / "passport_face.png"
    destination = archive_to_rejected(folder, "passport_face", ghost)
    # The destination wasn't materialised, but no exception.
    assert destination.parent.is_dir()
    assert not destination.exists()
