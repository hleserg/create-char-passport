"""Tests for the props-phase wizard logic (HLE-734)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from create_char_passport.config import get_settings
from create_char_passport.gen import GenerationResult, SceneId, default_composition
from create_char_passport.state import PropEntry, PropShot, blank_state
from create_char_passport.storage import REJECTED_DIR, character_dir, save_state
from create_char_passport.wizard import generation, props


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
        self, prompt_layers, refs, outfit_conflict=False, *, output_path, model=None, meter=None
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


def _styled(state) -> None:
    (character_dir(state.character_id) / "refs/style.png").write_bytes(b"style")
    state.style_ref = "refs/style.png"


def _with_prop(state, *, shots: int = 1) -> None:
    state.props_enabled = True
    state.props = [PropEntry(id="1", name="sword", shots=[PropShot() for _ in range(shots)])]


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def test_generate_prop_shot_style_only_no_character(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _styled(state)
    _with_prop(state)
    state.props[0].shots[0].prompt = "a glowing rune-etched longsword"
    fake = _Capture()
    monkeypatch.setattr(generation, "generate_image", fake)
    result = props.generate_prop_shot(state, 0, 1)
    assert result.ok
    assert state.props[0].shots[0].ref == "refs/prop_1_shot_1.png"
    call = fake.calls[0]
    assert call["roles"] == ["style"]  # ONLY style — no character refs
    # No character layers; the shot prompt rides the product-shot composition.
    assert call["layers"]["face"] == "" and call["layers"]["body"] == ""
    assert call["layers"]["outfit"] == "" and call["layers"]["expression"] == ""
    assert call["layers"]["composition"].startswith(default_composition(SceneId.PRODUCT_SHOT))
    assert "rune-etched longsword" in call["layers"]["composition"]


def test_generate_prop_shot_without_style_still_runs(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _with_prop(state)  # no style ref set
    monkeypatch.setattr(generation, "generate_image", _Capture())
    result = props.generate_prop_shot(state, 0, 1)
    assert result.ok  # a prop needs no refs at all
    assert state.props[0].shots[0].ref == "refs/prop_1_shot_1.png"


def test_generate_prop_shot_failure_leaves_no_ref(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _styled(state)
    _with_prop(state)
    monkeypatch.setattr(generation, "generate_image", _Capture(ok=False))
    result = props.generate_prop_shot(state, 0, 1)
    assert not result.ok
    assert state.props[0].shots[0].ref is None


def test_generate_prop_shot_archives_previous(
    bucket: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = blank_state("Conan")
    save_state(state)
    _styled(state)
    _with_prop(state)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    props.generate_prop_shot(state, 0, 1)
    props.generate_prop_shot(state, 0, 1)  # regen
    assert list(
        (character_dir(state.character_id) / REJECTED_DIR).glob("prop_1_shot_1_attempt*.png")
    )


def test_generate_prop_shot_bad_index_raises(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_prop(state)
    with pytest.raises(IndexError, match="prop index out of range"):
        props.generate_prop_shot(state, 9, 1)
    with pytest.raises(IndexError, match="prop shot index out of range"):
        props.generate_prop_shot(state, 0, 5)


# --------------------------------------------------------------------------- #
# Shots add / delete / cap
# --------------------------------------------------------------------------- #
def test_add_prop_shot_capped(bucket: Path) -> None:
    state = blank_state("Conan")
    _with_prop(state, shots=0)
    for _ in range(props.MAX_PROP_SHOTS + 2):
        props.add_prop_shot(state, 0)
    assert len(state.props[0].shots) == props.MAX_PROP_SHOTS


def test_delete_prop_shot_and_has_generation(bucket: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state = blank_state("Conan")
    save_state(state)
    _styled(state)
    _with_prop(state)
    monkeypatch.setattr(generation, "generate_image", _Capture())
    assert props.shot_has_generation(state, 0, 1) is False
    props.generate_prop_shot(state, 0, 1)
    assert props.shot_has_generation(state, 0, 1) is True
    props.delete_prop_shot(state, 0, 1)
    assert len(state.props[0].shots) == 0
    props.delete_prop_shot(state, 0, 9)  # out of range → no-op


# --------------------------------------------------------------------------- #
# Cursor helpers
# --------------------------------------------------------------------------- #
def test_cursor_helpers(bucket: Path) -> None:
    state = blank_state("Conan")
    state.props_enabled = True
    state.props = [PropEntry(id="1", name="a"), PropEntry(id="2", name="b")]
    assert props.first_prop_step(state) == "prop_1_shot_1"
    assert props.current_prop_index(state) is None
    state.current_step = "prop_2_shot_1"
    assert props.current_prop_index(state) == 1
    state.current_step = "prop_2_shot_3"  # any shot resolves to its prop
    assert props.current_prop_index(state) == 1
    assert props.adjacent_prop_step(state, 1, forward=True) is None
    assert props.adjacent_prop_step(state, 1, forward=False) == "prop_1_shot_1"
    assert props.adjacent_prop_step(state, 0, forward=True) == "prop_2_shot_1"


def test_first_prop_step_empty(bucket: Path) -> None:
    assert props.first_prop_step(blank_state("Conan")) is None
