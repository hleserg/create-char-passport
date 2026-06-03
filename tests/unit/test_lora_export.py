"""Tests for the LoRA-ready golden-set export (HLE-805, epic HLE-802)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult
from create_char_passport.screens import handlers
from create_char_passport.screens.router import ScreenId, WizardSession
from create_char_passport.state import (
    OutfitEntry,
    OutfitRefs,
    PromptLayers,
    PropEntry,
    PropShot,
    StepRecord,
    blank_state,
)
from create_char_passport.storage import character_asset, character_dir, save_state
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


def _write_ref(state, rel: str) -> str:
    """Create a stub image at a relative path inside the character bucket."""
    path = character_asset(state.character_id, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"img")
    return rel


def _identity_ready(state) -> None:
    """Approve passport face+body + style ref so dataset identity refs exist."""
    for key in ("passport_face", "passport_body"):
        _write_ref(state, f"refs/{key}.png")
        state.steps[key] = StepRecord(
            last_path=f"refs/{key}.png",
            approved_path=f"refs/{key}.png",
            prompt_layers=PromptLayers(style=_STYLE_MARKER, face="rugged barbarian", body="tall"),
        )
    _write_ref(state, "refs/style.png")
    state.style_ref = "refs/style.png"
    state.prompt_layers.style = _STYLE_MARKER
    state.prompt_layers.face = "rugged barbarian, blue eyes"


def _approved_dataset(state, compositions: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
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


def test_content_caption_collapses_interior_whitespace() -> None:
    # An embedded newline / double space must never reach the single-line sidecar.
    layers = PromptLayers(face="rugged   barbarian", composition="full body,\nwalking")
    assert (
        content_caption(layers, "conan_char") == "conan_char, rugged barbarian, full body, walking"
    )


# --------------------------------------------------------------------------- #
# Golden-set collection
# --------------------------------------------------------------------------- #
def test_export_collects_whole_golden_set(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    # base emotion + one series emotion (both blocks enabled)
    state.emotions.enabled = True
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.ref = _write_ref(state, "refs/base_emotion.png")
    state.emotions.items[0].ref = _write_ref(state, "refs/emotion_0.png")
    # one outfit with front + back scenes
    state.outfits_enabled = True
    state.outfits.append(
        OutfitEntry(
            id="1",
            prompt="battered leather armor",
            refs=OutfitRefs(
                front_full=_write_ref(state, "refs/outfit_1_front.png"),
                back_full=_write_ref(state, "refs/outfit_1_back.png"),
            ),
        )
    )
    _approved_dataset(state, ["full body, walking pose", "head and shoulders"], monkeypatch)

    out = bucket / "export_out"
    result = export_lora_dataset(state, out)
    # 2 passport + 1 base emotion + 1 series emotion + 2 outfit scenes + 2 dataset
    assert result.count == 8
    assert len(list(out.glob("*.png"))) == 8
    assert len(list(out.glob("*.txt"))) == 8
    captions = [t.read_text(encoding="utf-8") for t in sorted(out.glob("*.txt"))]
    # STYLE never leaks into ANY caption.
    assert all(_STYLE_MARKER not in c for c in captions)
    # The two outfit scenes are distinguished by their framing angle.
    assert any("back view" in c for c in captions)
    assert any("battered leather armor" in c for c in captions)
    # A dataset composition is captioned with its pose.
    assert any("walking pose" in c for c in captions)


def test_export_excludes_props_and_details(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    # A prop shot (no character) — must be excluded from a char-LoRA set.
    state.props_enabled = True
    state.props.append(
        PropEntry(
            id="1",
            name="sword",
            shots=[
                PropShot(what="sword", prompt="a sword", ref=_write_ref(state, "refs/prop.png"))
            ],
        )
    )
    _approved_dataset(state, ["walking"], monkeypatch)
    result = export_lora_dataset(state, bucket / "out")
    # 2 passport + 1 dataset = 3; prop is NOT counted.
    assert result.count == 3


def test_export_includes_refs_even_when_blocks_disabled(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A photo generated and then turned OFF is still a character image (nothing
    # is auto-deleted) — export collects by ref presence, NOT the enabled toggle.
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    state.emotions.enabled = False
    state.emotions.base_emotion.enabled = False
    state.emotions.base_emotion.ref = _write_ref(state, "refs/base_emotion.png")
    state.emotions.items[0].ref = _write_ref(state, "refs/emotion_0.png")
    state.outfits_enabled = False
    state.outfits.append(
        OutfitEntry(
            id="1", prompt="armor", refs=OutfitRefs(front_full=_write_ref(state, "refs/o.png"))
        )
    )
    _approved_dataset(state, ["walking"], monkeypatch)
    result = export_lora_dataset(state, bucket / "out")
    # 2 passport + base emotion + 1 series emotion + 1 outfit scene + 1 dataset = 6.
    assert result.count == 6


def test_emotion_caption_keeps_verbatim_value(bucket: Path) -> None:
    # The exact emotion label (incl. punctuation) must survive into the caption,
    # not be de-slugged ("angry, furious" -> "angry furious").
    state = blank_state("Conan")
    save_state(state)
    state.prompt_layers.face = "rugged barbarian"
    state.emotions.base_emotion.value = "excited, manic"
    state.emotions.base_emotion.ref = _write_ref(state, "refs/base_emotion.png")
    out = bucket / "out"
    export_lora_dataset(state, out)
    captions = [t.read_text(encoding="utf-8") for t in out.glob("*.txt")]
    assert any("excited, manic" in c for c in captions)  # comma preserved verbatim


def test_back_view_caption_drops_expression(bucket: Path) -> None:
    # The face is not visible in a back view, so no expression is captioned.
    state = blank_state("Conan")
    save_state(state)
    _write_ref(state, "refs/passport_back.png")
    state.steps["passport_back"] = StepRecord(
        last_path="refs/passport_back.png",
        approved_path="refs/passport_back.png",
        prompt_layers=PromptLayers(face="rugged barbarian", expression="neutral"),
    )
    out = bucket / "out"
    export_lora_dataset(state, out)
    caption = (out / "000.txt").read_text(encoding="utf-8")
    assert "back view" in caption
    assert "neutral" not in caption  # expression dropped for a back view


def test_emotion_caption_uses_base_outfit_not_active(bucket: Path) -> None:
    # Emotion portraits are shot in the BASE outfit; their caption must reflect
    # that, not whatever outfit is active at export time (active drifts past base
    # once the outfits phase runs).
    state = blank_state("Conan")
    save_state(state)
    state.base_outfit.prompt = "simple brown tunic"
    state.prompt_layers.face = "rugged barbarian"
    state.emotions.enabled = True
    state.emotions.base_emotion.enabled = True
    state.emotions.base_emotion.value = "angry"
    state.emotions.base_emotion.ref = _write_ref(state, "refs/base_emotion.png")
    # Simulate post-outfits navigation: a non-base outfit is active.
    state.outfits.append(OutfitEntry(id="1", prompt="battered leather armor"))
    state.active_outfit_id = "1"

    out = bucket / "out"
    export_lora_dataset(state, out)
    captions = [t.read_text(encoding="utf-8") for t in out.glob("*.txt")]
    assert any("simple brown tunic" in c for c in captions)  # base outfit = ground truth
    assert all("battered leather armor" not in c for c in captions)  # active outfit must NOT leak


def test_passport_caption_strips_generation_negatives(bucket: Path) -> None:
    # The stored composition is the full generation prompt (with "no text, no
    # panel border" negatives). A trainer reads negatives as positive tokens, so
    # the caption must carry a short clean framing instead.
    state = blank_state("Conan")
    save_state(state)
    verbose = (
        "Front facing portrait, head and shoulders, plain neutral grey background, "
        "no text, no speech bubbles, no panel border, no frame, no lettering"
    )
    _write_ref(state, "refs/passport_face.png")
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png",
        approved_path="refs/passport_face.png",
        prompt_layers=PromptLayers(
            style=_STYLE_MARKER, face="rugged barbarian", composition=verbose
        ),
    )
    out = bucket / "out"
    export_lora_dataset(state, out)
    caption = (out / "000.txt").read_text(encoding="utf-8")
    assert "no text" not in caption
    assert "no panel" not in caption
    assert "front view" in caption  # short clean framing substituted
    assert _STYLE_MARKER not in caption


def test_dataset_caption_is_clean_single_line(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    _approved_dataset(state, ["full body, walking pose, seen from the front"], monkeypatch)
    out = bucket / "out"
    export_lora_dataset(state, out)
    caption = next(
        t.read_text(encoding="utf-8")
        for t in out.glob("*.txt")
        if "walking pose" in t.read_text("utf-8")
    )
    assert "\n" not in caption  # single line
    assert "neutral grey background" not in caption  # BACKGROUND_DIRECTIVE stripped
    assert "no panel border" not in caption


def test_export_skips_unapproved_dataset(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    monkeypatch.setattr(generation, "generate_image", _fake_ok)
    state.dataset_compositions = ["walking", "sitting"]
    dataset.generate_dataset_frame(state, 0)
    dataset.approve_dataset_frame(state, 0)
    dataset.generate_dataset_frame(state, 1)  # generated but NOT approved
    result = export_lora_dataset(state, bucket / "out")
    # 2 passport + 1 approved dataset = 3 (the unapproved dataset frame is skipped).
    assert result.count == 3


def test_export_counts_missing_files_as_skipped(bucket: Path) -> None:
    # A frame collected from state whose image is gone on disk is counted, not
    # silently dropped, so a partial export is distinguishable from a complete one.
    state = blank_state("Conan")
    save_state(state)
    _write_ref(state, "refs/passport_face.png")
    state.steps["passport_face"] = StepRecord(
        last_path="refs/passport_face.png", approved_path="refs/passport_face.png"
    )
    # passport_body approved in state but the file was never written.
    state.steps["passport_body"] = StepRecord(
        last_path="refs/passport_body.png", approved_path="refs/passport_body.png"
    )
    result = export_lora_dataset(state, bucket / "out")
    assert result.count == 1
    assert result.skipped == 1


def test_export_zip_returns_path_and_result(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    _approved_dataset(state, ["walking"], monkeypatch)
    zip_path, result = export_lora_zip(state)
    assert result.count == 3  # 2 passport + 1 dataset
    assert zip_path is not None
    assert Path(zip_path).is_file()
    assert zip_path.endswith(".zip")


def test_export_zip_rebuilds_staging(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A re-export must not accumulate stale frames in the staging dir.
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)
    _approved_dataset(state, ["walking", "sitting"], monkeypatch)
    export_lora_zip(state)
    staging = character_dir(state.character_id) / "lora_export"
    first = sorted(p.name for p in staging.glob("*.png"))
    export_lora_zip(state)  # second run
    assert sorted(p.name for p in staging.glob("*.png")) == first  # no duplicates


def test_export_zip_none_when_nothing_approved(bucket: Path) -> None:
    state = blank_state("Conan")
    save_state(state)
    zip_path, result = export_lora_zip(state)
    assert zip_path is None
    assert result.count == 0


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
    _identity_ready(state)
    _approved_dataset(state, ["walking", "sitting"], monkeypatch)
    session = WizardSession(current_screen=ScreenId.FINISH, character=state)
    path, note = handlers.on_export_lora(session)
    assert path is not None and Path(path).is_file()
    assert "4" in note  # 2 passport + 2 dataset
    assert "conan_char" in note


def test_on_export_lora_io_failure_degrades(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A disk/zip I/O error must surface as a friendly note, never a raw crash.
    state = blank_state("Conan")
    save_state(state)
    _identity_ready(state)

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(handlers, "export_lora_zip", _boom)
    session = WizardSession(current_screen=ScreenId.FINISH, character=state)
    path, note = handlers.on_export_lora(session)
    assert path is None
    assert "Не удалось" in note
