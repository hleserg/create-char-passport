"""Tests for the LoRA-ready dataset export (HLE-805, epic HLE-802)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.state import PromptLayers, StepRecord, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import dataset, generation
from create_char_passport.wizard.export import (
    content_caption,
    default_trigger,
    export_lora_dataset,
    export_lora_zip,
)

_STYLE_MARKER = "GRITTY_COMIC_STYLE_MARKER"


@pytest.fixture
def bucket(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("APP_BUCKET_PATH", str(tmp_path))
    get_settings.cache_clear()
    yield tmp_path


def _fake_ok(prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None):
    Path(output_path).write_bytes(b"img")
    return GenerationResult(image_path=str(output_path), ok=True)


def _ready(state) -> None:
    """Approve passport face+body + style ref so identity refs are complete."""
    cdir = character_dir(state.character_id)
    for key in ("passport_face", "passport_body"):
        (cdir / f"refs/{key}.png").write_bytes(b"img")
        state.steps[key] = StepRecord(last_path=f"refs/{key}.png", approved_path=f"refs/{key}.png")
    (cdir / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


def _with_dataset(state, compositions: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """Generate + approve every composition so the approved/ archive is populated."""
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    state.prompt_layers.style = _STYLE_MARKER
    state.prompt_layers.face = "a rugged barbarian, blue eyes"
    state.dataset_compositions = list(compositions)
    for i in range(len(compositions)):
        dataset.generate_dataset_frame(state, i)
        dataset.approve_dataset_frame(state, i)


# --------------------------------------------------------------------------- #
# Caption + trigger (pure)
# --------------------------------------------------------------------------- #
def test_default_trigger_slugs_name(bucket: Path) -> None:
    assert default_trigger(blank_state("Conan")) == "conan_char"
    assert default_trigger(blank_state("Red Sonja")) == "red_sonja_char"


def test_default_trigger_falls_back_to_id(bucket: Path) -> None:
    state = blank_state("")
    trigger = default_trigger(state)
    assert trigger.endswith("_char")  # falls back to the character id when name is blank
    assert trigger != "_char"  # the id itself is non-empty


def test_content_caption_excludes_style_and_drops_empty() -> None:
    layers = PromptLayers(
        style=_STYLE_MARKER,
        face="rugged barbarian",
        body="",
        outfit="fur cloak",
        expression="",
        composition="full body, walking",
    )
    caption = content_caption(layers, "conan_char")
    assert caption == "conan_char, rugged barbarian, fur cloak, full body, walking"
    assert _STYLE_MARKER not in caption  # STYLE is never captioned


def test_content_caption_trigger_only_when_no_content() -> None:
    assert content_caption(PromptLayers(style=_STYLE_MARKER), "conan_char") == "conan_char"


def test_content_caption_no_trigger_no_dangling_comma() -> None:
    layers = PromptLayers(face="rugged barbarian")
    assert content_caption(layers, "  ") == "rugged barbarian"


# --------------------------------------------------------------------------- #
# Dataset staging
# --------------------------------------------------------------------------- #
def test_export_writes_image_and_content_caption(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_dataset(state, ["full body, walking pose", "head and shoulders"], monkeypatch)

    out = bucket / "export_out"
    result = export_lora_dataset(state, out)
    assert result.count == 2
    assert result.trigger == "conan_char"
    assert sorted(p.name for p in out.glob("*.png")) == ["000.png", "001.png"]
    caption0 = (out / "000.txt").read_text(encoding="utf-8")
    assert caption0.startswith("conan_char, ")
    assert "walking pose" in caption0
    assert _STYLE_MARKER not in caption0  # style layer dropped from every caption


def test_export_skips_unapproved_frames(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    state.dataset_compositions = ["walking", "sitting"]
    dataset.generate_dataset_frame(state, 0)
    dataset.approve_dataset_frame(state, 0)
    dataset.generate_dataset_frame(state, 1)  # generated but NOT approved

    result = export_lora_dataset(state, bucket / "out")
    assert result.count == 1  # only the approved frame is staged


def test_export_zip_returns_path_and_count(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_dataset(state, ["walking"], monkeypatch)
    zip_path, count = export_lora_zip(state)
    assert count == 1
    assert zip_path is not None
    assert Path(zip_path).is_file()
    assert zip_path.endswith(".zip")


def test_export_zip_rebuilds_staging(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A re-export must not accumulate stale frames in the staging dir.
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_dataset(state, ["walking", "sitting"], monkeypatch)
    export_lora_zip(state)
    staging = character_dir(state.character_id) / "lora_export"
    first = sorted(p.name for p in staging.glob("*.png"))
    export_lora_zip(state)  # second run
    assert sorted(p.name for p in staging.glob("*.png")) == first  # no duplicates


def test_export_zip_none_when_no_approved(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    zip_path, count = export_lora_zip(state)
    assert zip_path is None
    assert count == 0


# --------------------------------------------------------------------------- #
# Finish-screen handler
# --------------------------------------------------------------------------- #
def test_on_export_lora_no_character() -> None:
    assert handlers.on_export_lora(WizardSession()) == (None, "")


def test_on_export_lora_no_frames(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    session = WizardSession(current_screen=ScreenId.FINISH, character=state)
    path, note = handlers.on_export_lora(session)
    assert path is None
    assert "Нет утверждённых" in note


def test_on_export_lora_ok(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _ready(state)
    _with_dataset(state, ["walking", "sitting"], monkeypatch)
    session = WizardSession(current_screen=ScreenId.FINISH, character=state)
    path, note = handlers.on_export_lora(session)
    assert path is not None and Path(path).is_file()
    assert "2" in note
    assert "conan_char" in note
