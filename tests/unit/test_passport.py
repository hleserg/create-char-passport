"""Tests for the passport-phase logic (``wizard/passport.py``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.state import CostLedger, StepRecord, blank_state
from create_char_passport.storage import REJECTED_DIR, character_dir, save_state
from create_char_passport.wizard import passport


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def _approved(state: object, step_key: str) -> None:
    """Mark ``step_key`` approved and drop a real ref file on disk."""
    char_dir = character_dir(state.character_id)  # type: ignore[attr-defined]
    rel = f"refs/{step_key}.png"
    (char_dir / rel).write_bytes(b"img")
    state.steps[step_key] = StepRecord(last_path=rel, approved_path=rel)  # type: ignore[attr-defined]


def _fake_ok(written: list[Path]):
    def fake(prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
        Path(output_path).write_bytes(b"new-image")
        written.append(Path(output_path))
        if meter is not None:
            meter.image_usd += 0.05
            meter.image_calls += 1
        return GenerationResult(image_path=str(output_path), ok=True)

    return fake


def _fake_fail(prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    return GenerationResult(image_path=None, ok=False, error="boom — retry")


# --------------------------------------------------------------------------- #
# Frame metadata
# --------------------------------------------------------------------------- #
def test_passport_index_and_ref_frames() -> None:
    assert passport.passport_index("passport_face") == 0
    assert passport.passport_index("passport_3q") == 4
    assert passport.is_ref_frame("passport_face") is True
    assert passport.is_ref_frame("passport_body") is True
    assert passport.is_ref_frame("passport_profile") is False


def test_editable_layers_per_frame() -> None:
    assert passport.editable_layers("passport_face") == frozenset({"face", "outfit"})
    assert passport.editable_layers("passport_body") == frozenset({"body", "outfit"})
    assert passport.editable_layers("passport_profile") == frozenset()
    assert passport.editable_layers("passport_3q") == frozenset()


def test_frame_metadata_accessors() -> None:
    assert "Фас-портрет" in passport.frame_title("passport_face")
    assert "профиль" in passport.frame_criterion("passport_profile").lower()


def test_non_passport_step_raises() -> None:
    for fn in (
        passport.passport_index,
        passport.editable_layers,
        passport.frame_title,
        passport.frame_criterion,
    ):
        with pytest.raises(ValueError, match="not a passport step"):
            fn("base_emotion")


# --------------------------------------------------------------------------- #
# Cursor + navigation
# --------------------------------------------------------------------------- #
def test_first_pending_passport_picks_earliest() -> None:
    state = blank_state("Heron")
    state.steps["passport_body"] = StepRecord(need_regen=True)
    state.steps["passport_face"] = StepRecord(need_regen=True)
    assert passport.first_pending_passport(state) == "passport_face"


def test_first_pending_passport_none_when_clean() -> None:
    assert passport.first_pending_passport(blank_state("Heron")) is None


def test_current_passport_step_resolution() -> None:
    state = blank_state("Heron")
    assert passport.current_passport_step(state) == "passport_face"  # default
    state.current_step = "passport_profile"
    assert passport.current_passport_step(state) == "passport_profile"  # clamps to saved
    state.current_step = "base_emotion"  # non-passport → first frame
    assert passport.current_passport_step(state) == "passport_face"
    state.steps["passport_back"] = StepRecord(need_regen=True)  # gate wins
    state.current_step = "passport_profile"
    assert passport.current_passport_step(state) == "passport_back"


def test_next_previous_passport_step_boundaries() -> None:
    assert passport.next_passport_step("passport_face") == "passport_body"
    assert passport.next_passport_step("passport_3q") is None
    assert passport.previous_passport_step("passport_face") is None
    assert passport.previous_passport_step("passport_body") == "passport_face"


# --------------------------------------------------------------------------- #
# Reference schedule (§3.5 / §4)
# --------------------------------------------------------------------------- #
def test_passport_refs_schedule(bucket: Path) -> None:
    state = blank_state("Heron")
    save_state(state)
    _approved(state, "passport_face")
    _approved(state, "passport_body")
    assert passport.passport_refs(state, "passport_face") == []  # frame 1: no refs
    body_refs = passport.passport_refs(state, "passport_body")
    assert [r.role for r in body_refs] == ["face"]  # frame 2: face only
    full = passport.passport_refs(state, "passport_profile")
    assert [r.role for r in full] == ["face", "body"]  # frames 3-5: face + body
    assert all(Path(r.path).is_file() for r in full)


def test_passport_refs_skips_unapproved_or_missing(bucket: Path) -> None:
    state = blank_state("Heron")
    save_state(state)
    # face approved on disk, body only has a (non-approved) last_path
    _approved(state, "passport_face")
    state.steps["passport_body"] = StepRecord(last_path="refs/passport_body.png")
    refs = passport.passport_refs(state, "passport_3q")
    assert [r.role for r in refs] == ["face"]  # body not approved → skipped
    # approved_path pointing at a missing file is skipped too
    state.steps["passport_body"] = StepRecord(approved_path="refs/ghost.png")
    assert [r.role for r in passport.passport_refs(state, "passport_3q")] == ["face"]


# --------------------------------------------------------------------------- #
# Layer edits
# --------------------------------------------------------------------------- #
def test_apply_layer_edit_only_touches_editable_layers() -> None:
    state = blank_state("Heron")
    state.prompt_layers.face = "old face"
    state.prompt_layers.body = "old body"
    # On frame 1 (face): face + outfit editable, body frozen.
    passport.apply_layer_edit(
        state, "passport_face", face="  new face  ", body="HACK", outfit="  cloak  "
    )
    assert state.prompt_layers.face == "new face"  # written + stripped
    assert state.prompt_layers.body == "old body"  # frozen → untouched
    assert state.base_outfit.prompt == "cloak"
    # On frame 2 (body): body + outfit editable, face frozen.
    passport.apply_layer_edit(state, "passport_body", face="HACK", body="  toned  ", outfit="armor")
    assert state.prompt_layers.body == "toned"  # written + stripped
    assert state.prompt_layers.face == "new face"  # frozen → untouched
    assert state.base_outfit.prompt == "armor"
    # On frame 3 nothing is editable.
    passport.apply_layer_edit(state, "passport_profile", face="X", body="Y", outfit="Z")
    assert state.prompt_layers.face == "new face"
    assert state.prompt_layers.body == "toned"
    assert state.base_outfit.prompt == "armor"


# --------------------------------------------------------------------------- #
# Generate / regenerate
# --------------------------------------------------------------------------- #
def test_generate_first_frame_success(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Heron")
    save_state(state)
    written: list[Path] = []
    monkeypatch.setattr(passport, "generate_image", _fake_ok(written))
    meter = CostLedger()
    result = passport.generate_passport_frame(state, "passport_face", regenerate=False, meter=meter)
    assert result.ok
    record = state.steps["passport_face"]
    assert record.last_path == "refs/passport_face.png"
    assert record.approved_path is None  # fresh gen is unapproved
    assert (character_dir(state.character_id) / "refs/passport_face.png").is_file()
    assert meter.image_calls == 1  # billed


def test_generate_failure_preserves_previous_and_prompt(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    _approved(state, "passport_face")  # an existing good frame
    monkeypatch.setattr(passport, "generate_image", _fake_fail)
    result = passport.generate_passport_frame(state, "passport_face", regenerate=True)
    assert not result.ok
    record = state.steps["passport_face"]
    assert record.last_path == "refs/passport_face.png"  # unchanged
    assert record.approved_path == "refs/passport_face.png"  # previous frame kept
    assert (character_dir(state.character_id) / "refs/passport_face.png").is_file()
    # no leftover pending file
    assert not (character_dir(state.character_id) / "refs/passport_face.png.pending").exists()


def test_regenerate_archives_previous_to_rejected(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(passport, "generate_image", _fake_ok([]))
    passport.generate_passport_frame(state, "passport_face", regenerate=False)
    passport.approve_passport_frame(state, "passport_face")
    passport.generate_passport_frame(state, "passport_face", regenerate=True)
    rejected = character_dir(state.character_id) / REJECTED_DIR
    archived = list(rejected.glob("passport_face_attempt*.png"))
    assert len(archived) == 1  # old frame preserved, not overwritten
    assert state.steps["passport_face"].approved_path is None  # must re-approve


def test_regenerate_ref_frame_flags_downstream_stale(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(passport, "generate_image", _fake_ok([]))
    _approved(state, "passport_face")
    _approved(state, "passport_body")
    _approved(state, "passport_profile")
    passport.generate_passport_frame(state, "passport_face", regenerate=True)
    assert state.steps["passport_body"].stale is True
    assert state.steps["passport_profile"].stale is True


def test_regenerate_non_ref_frame_does_not_flag(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(passport, "generate_image", _fake_ok([]))
    _approved(state, "passport_back")
    _approved(state, "passport_3q")
    passport.generate_passport_frame(state, "passport_back", regenerate=True)
    assert state.steps["passport_3q"].stale is False


def test_regenerate_clears_own_flags(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Heron")
    save_state(state)
    monkeypatch.setattr(passport, "generate_image", _fake_ok([]))
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png", need_regen=True, stale=True
    )
    (character_dir(state.character_id) / "refs/passport_face.png").write_bytes(b"old")
    passport.generate_passport_frame(state, "passport_face", regenerate=True)
    assert state.steps["passport_face"].need_regen is False
    assert state.steps["passport_face"].stale is False


# --------------------------------------------------------------------------- #
# Approve + freeze
# --------------------------------------------------------------------------- #
def test_approve_without_generation_raises() -> None:
    state = blank_state("Heron")
    with pytest.raises(ValueError, match="no generation"):
        passport.approve_passport_frame(state, "passport_face")


def test_approve_face_sets_approved_path_clears_flags() -> None:
    state = blank_state("Heron")
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png", need_regen=True, stale=True
    )
    passport.approve_passport_frame(state, "passport_face")
    record = state.steps["passport_face"]
    assert record.approved_path == "refs/passport_face.png"
    assert record.need_regen is False
    assert record.stale is False
    assert state.base_outfit.frozen is False  # face approve does NOT freeze outfit


def test_approve_body_freezes_base_outfit() -> None:
    state = blank_state("Heron")
    state.steps["passport_body"] = StepRecord(last_path="refs/passport_body.png")
    passport.approve_passport_frame(state, "passport_body")
    assert state.base_outfit.frozen is True
    assert state.base_outfit.ref == "refs/passport_body.png"


def test_all_passport_approved() -> None:
    state = blank_state("Heron")
    assert passport.all_passport_approved(state) is False
    for key in ("passport_face", "passport_body", "passport_profile", "passport_back"):
        state.steps[key] = StepRecord(approved_path=f"refs/{key}.png")
    assert passport.all_passport_approved(state) is False  # 3q missing
    state.steps["passport_3q"] = StepRecord(approved_path="refs/passport_3q.png")
    assert passport.all_passport_approved(state) is True


def test_cascade_warning() -> None:
    state = blank_state("Heron")
    state.steps["passport_back"] = StepRecord(approved_path="refs/x.png", stale=True)
    assert passport.cascade_warning(state, "passport_back") == passport.CASCADE_WARNING
    assert passport.cascade_warning(state, "passport_face") is None
