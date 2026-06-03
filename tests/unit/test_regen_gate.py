"""Tests for the need_regen gate + its clearing (HLE-731 §Г)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens.handlers import enforce_regen_gate
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.state import OutfitEntry, OutfitRefs, StepRecord, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import dataset, generation, outfits


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
    return GenerationResult(image_path=str(output_path), ok=True)


def _ready(state) -> None:
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


# --------------------------------------------------------------------------- #
# Gate redirect
# --------------------------------------------------------------------------- #
def test_gate_redirects_to_earlier_flagged_step(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    state.outfits_enabled = True
    state.outfits.append(OutfitEntry(id="1"))
    state.steps["outfit_1"] = StepRecord(last_path="refs/x.png", need_regen=True)
    session = WizardSession(current_screen=ScreenId.DATASET, character=state)
    out = enforce_regen_gate(session)
    assert out.current_screen is ScreenId.OUTFITS  # jumped back to the flagged step's screen
    assert state.current_step == "outfit_1"
    assert "доисправьте" in out.notice


def test_gate_noop_when_nothing_flagged(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    session = WizardSession(current_screen=ScreenId.DATASET, character=state)
    out = enforce_regen_gate(session)
    assert out.current_screen is ScreenId.DATASET  # untouched


def test_gate_no_character_is_noop() -> None:
    assert enforce_regen_gate(WizardSession()).character is None


# --------------------------------------------------------------------------- #
# Clearing (approve clears the flag, §Г)
# --------------------------------------------------------------------------- #
def test_dataset_approve_clears_need_regen(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    state.dataset_compositions = ["walking"]
    dataset.generate_dataset_frame(state, 0)
    state.steps["dataset_0"].need_regen = True  # simulate an accepted AI-edit flag
    dataset.approve_dataset_frame(state, 0)
    assert state.steps["dataset_0"].need_regen is False


def test_outfit_back_scene_regen_clears_need_regen(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Regenerating ANY scene (not just front-full) clears the gate flag, so a
    # back/profile-only regen doesn't re-redirect (§Г papercut fix).
    from create_char_passport.gen import SceneId

    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    state.outfits_enabled = True
    state.outfits.append(OutfitEntry(id="1", prompt="armor"))
    state.steps["outfit_1"] = StepRecord(last_path="refs/x.png", need_regen=True)
    outfits.generate_outfit_scene(state, 0, SceneId.BACK_FULL)
    assert state.steps["outfit_1"].need_regen is False


def test_outfit_approve_clears_need_regen(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    state.outfits_enabled = True
    state.outfits.append(
        OutfitEntry(
            id="1",
            prompt="armor",
            refs=OutfitRefs(front_full="refs/f.png", back_full="refs/b.png"),
        )
    )
    state.steps["outfit_1"] = StepRecord(last_path="refs/f.png", need_regen=True)
    assert outfits.approve_outfit(state, 0) is True
    assert state.steps["outfit_1"].need_regen is False
