"""Tests for the outfits-phase wizard logic (HLE-733)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult, SceneId
from create_char_passport.state import OutfitEntry, StepRecord, blank_state
from create_char_passport.storage import REJECTED_DIR, character_dir, save_state
from create_char_passport.wizard import generation, outfits


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


class _Capture:
    """A fake generate_image that writes the file and records its call args."""

    def __init__(self, *, ok: bool = True) -> None:
        self.ok = ok
        self.calls: list[dict[str, object]] = []

    def __call__(self, prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
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
    """Approve passport face+body and set a style ref so identity_refs is complete."""
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


def _with_outfit(state, *, complex_: bool = False) -> None:
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="1", prompt="red cloak", complex=complex_)]


# --------------------------------------------------------------------------- #
# Scene set + complexity
# --------------------------------------------------------------------------- #
def test_outfit_scenes_simple_vs_complex() -> None:
    assert outfits.outfit_scenes(OutfitEntry(id="1")) == (SceneId.FRONT_FULL, SceneId.BACK_FULL)
    assert outfits.outfit_scenes(OutfitEntry(id="1", complex=True)) == (
        SceneId.FRONT_FULL,
        SceneId.BACK_FULL,
        SceneId.PROFILE_FULL,
    )


def test_set_complex_hides_and_restores_profile_without_deleting(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_outfit(state, complex_=True)
    state.outfits[0].refs.profile_full = "refs/outfit_1_profile_full.png"
    outfits.set_outfit_complex(state, 0, False)  # turn off
    assert state.outfits[0].complex is False
    assert SceneId.PROFILE_FULL not in outfits.outfit_scenes(state.outfits[0])
    assert state.outfits[0].refs.profile_full == "refs/outfit_1_profile_full.png"  # not deleted
    outfits.set_outfit_complex(state, 0, True)  # turn back on
    assert SceneId.PROFILE_FULL in outfits.outfit_scenes(state.outfits[0])
    assert state.outfits[0].refs.profile_full == "refs/outfit_1_profile_full.png"  # restored


# --------------------------------------------------------------------------- #
# Scene generation
# --------------------------------------------------------------------------- #
def test_generate_scene_sets_ref_active_and_identity_refs(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state)
    fake = _Capture()
    monkeypatch.setattr(generation, "generate_image", fake)
    result = outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)
    assert result.ok
    assert state.outfits[0].refs.front_full == "refs/outfit_1_front_full.png"
    assert state.active_outfit_id == "1"  # selected before build (OUTFIT layer)
    assert fake.calls[0]["roles"] == ["style", "face", "body"]  # identity refs
    assert fake.calls[0]["outfit_conflict"] is True
    # front-full writes the representative step record (resume / can_advance).
    assert state.steps["outfit_1"].last_path == "refs/outfit_1_front_full.png"


def test_generate_scenes_do_not_clobber_each_other(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)
    outfits.generate_outfit_scene(state, 0, SceneId.BACK_FULL)
    cdir = character_dir(state.character_id)
    assert (cdir / "refs/outfit_1_front_full.png").is_file()
    assert (cdir / "refs/outfit_1_back_full.png").is_file()
    assert state.outfits[0].refs.front_full != state.outfits[0].refs.back_full


def test_generate_scene_failure_leaves_no_ref(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state)
    monkeypatch.setattr(generation, "generate_image", _Capture(ok=False))
    result = outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)
    assert not result.ok
    assert state.outfits[0].refs.front_full is None


def test_generate_scene_archives_previous(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)
    outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)  # regen
    cdir = character_dir(state.character_id)
    assert list((cdir / REJECTED_DIR).glob("outfit_1_front_full_attempt*.png"))


def test_generate_scene_bad_index_raises(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_outfit(state)
    with pytest.raises(IndexError, match="out of range"):
        outfits.generate_outfit_scene(state, 9, SceneId.FRONT_FULL)


# --------------------------------------------------------------------------- #
# Detail generation
# --------------------------------------------------------------------------- #
def test_generate_detail_uses_style_and_outfit_only(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state, complex_=True)
    fake = _Capture()
    monkeypatch.setattr(generation, "generate_image", fake)
    outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)  # need front first
    outfits.add_outfit_detail(state, 0)
    state.outfits[0].details[0].prompt = "ornate buckle"
    result = outfits.generate_outfit_detail(state, 0, 1)
    assert result.ok
    assert state.outfits[0].details[0].ref == "refs/outfit_1_detail_1.png"
    call = fake.calls[-1]
    assert sorted(call["roles"]) == ["outfit", "style"]  # NO face/body
    assert call["outfit_conflict"] is False
    assert call["layers"]["face"] == "" and call["layers"]["body"] == ""
    assert call["layers"]["expression"] == ""


def test_generate_detail_without_front_fails(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state, complex_=True)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    outfits.add_outfit_detail(state, 0)
    result = outfits.generate_outfit_detail(state, 0, 1)  # no front_full yet
    assert not result.ok
    assert state.outfits[0].details[0].ref is None


def test_add_delete_detail_and_has_generation(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_outfit(state, complex_=True)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    assert outfits.add_outfit_detail(state, 0) == 1
    assert outfits.add_outfit_detail(state, 0) == 2
    assert outfits.detail_has_generation(state, 0, 1) is False
    outfits.generate_outfit_scene(state, 0, SceneId.FRONT_FULL)
    outfits.generate_outfit_detail(state, 0, 1)
    assert outfits.detail_has_generation(state, 0, 1) is True
    outfits.delete_outfit_detail(state, 0, 1)
    assert len(state.outfits[0].details) == 1
    outfits.delete_outfit_detail(state, 0, 9)  # out of range → no-op


# --------------------------------------------------------------------------- #
# Approval gating
# --------------------------------------------------------------------------- #
def test_required_scenes_present_keys_on_presence_not_approval() -> None:
    outfit = OutfitEntry(id="1")  # simple → front + back
    assert outfits.required_scenes_present(outfit) is False
    outfit.refs.front_full = "a.png"
    assert outfits.required_scenes_present(outfit) is False
    outfit.refs.back_full = "b.png"
    assert outfits.required_scenes_present(outfit) is True
    # the approved flags must NOT affect the gate (they are optimization-only).
    outfit.refs.front_full_approved = False
    assert outfits.required_scenes_present(outfit) is True


def test_required_scenes_complex_needs_profile() -> None:
    outfit = OutfitEntry(id="1", complex=True)
    outfit.refs.front_full = "a.png"
    outfit.refs.back_full = "b.png"
    assert outfits.required_scenes_present(outfit) is False  # profile missing
    outfit.refs.profile_full = "c.png"
    assert outfits.required_scenes_present(outfit) is True


def test_missing_outfit_scenes(bucket: Path) -> None:
    state = blank_state("Conan")
    assert outfits.missing_outfit_scenes(state) == []  # block off
    _with_outfit(state)
    assert outfits.missing_outfit_scenes(state) == ["red cloak — front_full", "red cloak — back_full"]
    state.outfits[0].refs.front_full = "a.png"
    state.outfits[0].refs.back_full = "b.png"
    assert outfits.missing_outfit_scenes(state) == []


def test_approve_outfit_incomplete_is_noop(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_outfit(state)
    assert outfits.approve_outfit(state, 0) is False
    assert state.active_outfit_id == "base"  # unchanged


def test_approve_outfit_complete_sets_active_and_approved(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_outfit(state)
    state.outfits[0].refs.front_full = "a.png"
    state.outfits[0].refs.back_full = "b.png"
    assert outfits.approve_outfit(state, 0) is True
    assert state.active_outfit_id == "1"
    assert state.outfits[0].refs.front_full_approved is True
    assert state.outfits[0].refs.back_full_approved is True


def test_all_outfits_approved(bucket: Path) -> None:
    state = blank_state("Conan")
    assert outfits.all_outfits_approved(state) is True  # block off
    state.outfits_enabled = True
    state.outfits = [OutfitEntry(id="1", prompt="a"), OutfitEntry(id="2", prompt="b")]
    for o in state.outfits:
        o.refs.front_full = "f.png"
    assert outfits.all_outfits_approved(state) is False  # second missing back
    for o in state.outfits:
        o.refs.back_full = "b.png"
    assert outfits.all_outfits_approved(state) is True
