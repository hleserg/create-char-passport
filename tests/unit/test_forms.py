"""Tests for the pure character-data form logic."""

from __future__ import annotations

from pathlib import Path

from create_char_passport.state import OutfitDetail, OutfitRefs, PropShot, blank_state
from create_char_passport.storage import character_dir, save_state
from create_char_passport.wizard import (
    BASE_OUTFIT_PLACEHOLDER,
    ExtractedCharacter,
    base_outfit_display,
    character_from_extracted,
    emotion_rows,
    outfit_rows,
    prop_rows,
    saved_characters,
    set_base_emotion,
    set_emotions_enabled,
    set_outfits_enabled,
    set_props_enabled,
    sync_outfits,
    sync_props,
    table_from_state,
)
from create_char_passport.wizard.forms import apply_table


def _extracted() -> ExtractedCharacter:
    return ExtractedCharacter(
        name="Conan",
        table={"gender": "male", "build": "powerful", "skin": ""},
        face="broad face, blue eyes, black hair",
        body="powerful stocky build, scar on forearm",
        outfit="dark fur-trimmed leather tunic",
    )


def test_character_from_extracted_seeds_table_and_style() -> None:
    state = character_from_extracted(_extracted(), style_prompt="  inked comic  ")
    assert state.name == "Conan"
    table = table_from_state(state)
    assert table["gender"] == "male"
    assert table["build"] == "powerful"
    assert table["age"] == ""  # missing -> empty, user fills in
    assert state.prompt_layers.style == "inked comic"


def test_character_from_extracted_without_style() -> None:
    state = character_from_extracted(_extracted())
    assert state.prompt_layers.style == ""


def test_character_from_extracted_seeds_draft_layers() -> None:
    state = character_from_extracted(_extracted())
    assert state.prompt_layers.face == "broad face, blue eyes, black hair"
    assert state.prompt_layers.body == "powerful stocky build, scar on forearm"
    assert state.base_outfit.prompt == "dark fur-trimmed leather tunic"


def test_character_from_extracted_empty_drafts_stay_empty() -> None:
    state = character_from_extracted(ExtractedCharacter(name="Tyra"))
    assert state.prompt_layers.face == ""
    assert state.prompt_layers.body == ""
    assert state.base_outfit.prompt == ""


def test_apply_table_user_is_truth() -> None:
    state = character_from_extracted(_extracted())
    apply_table(state, {"gender": "female", "age": "50", "weapon": "axe"})
    table = table_from_state(state)
    assert table["gender"] == "female"
    assert table["age"] == "50"
    assert "weapon" not in table


def test_base_outfit_display_placeholder_then_value() -> None:
    state = blank_state("Conan")
    assert base_outfit_display(state) == BASE_OUTFIT_PLACEHOLDER
    state.base_outfit.prompt = "dark leather tunic"
    assert base_outfit_display(state) == "dark leather tunic"


def test_emotions_toggle_writes_nested_flag() -> None:
    state = blank_state("Conan")
    set_emotions_enabled(state, True)
    assert state.emotions.enabled is True
    rows = emotion_rows(state)
    assert [r[0] for r in rows] == ["neutral", "angry, furious", "smiling warmly"]
    assert rows[0][1] == "—"  # no ref yet


def test_emotion_rows_show_ref_when_present() -> None:
    state = blank_state("Conan")
    state.emotions.items[0].ref = "refs/emotion_neutral.png"
    assert emotion_rows(state)[0][1] == "refs/emotion_neutral.png"


def test_set_base_emotion() -> None:
    state = blank_state("Conan")
    set_base_emotion(state, True, "  grim, brooding ")
    assert state.emotions.base_emotion.enabled is True
    assert state.emotions.base_emotion.value == "grim, brooding"


def test_sync_outfits_adds_rows_with_ordinal_ids() -> None:
    state = blank_state("Conan")
    set_outfits_enabled(state, True)
    sync_outfits(state, [["plate armor", True], ["robe", False]])
    assert [o.id for o in state.outfits] == ["1", "2"]
    assert state.outfits[0].complex is True
    assert state.outfits[1].complex is False
    assert outfit_rows(state) == [["plate armor", True], ["robe", False]]


def test_sync_outfits_preserves_refs_and_details_by_position() -> None:
    state = blank_state("Conan")
    sync_outfits(state, [["plate armor", True]])
    state.outfits[0].refs = OutfitRefs(front_full="refs/outfit_1.png")
    state.outfits[0].details = [OutfitDetail(prompt="pauldron", ref="refs/d.png")]
    # Edit the prompt of the same (positional) row.
    sync_outfits(state, [["ornate plate armor", True]])
    assert state.outfits[0].prompt == "ornate plate armor"
    assert state.outfits[0].refs.front_full == "refs/outfit_1.png"
    assert state.outfits[0].details[0].prompt == "pauldron"


def test_sync_outfits_drops_blank_rows() -> None:
    state = blank_state("Conan")
    sync_outfits(state, [["robe", False], ["  ", True], [None, False]])
    assert [o.prompt for o in state.outfits] == ["robe"]


def test_sync_outfits_coerces_string_bool() -> None:
    state = blank_state("Conan")
    sync_outfits(state, [["robe", "true"], ["cloak", "no"]])
    assert state.outfits[0].complex is True
    assert state.outfits[1].complex is False


def test_sync_outfits_removal_shrinks_list() -> None:
    state = blank_state("Conan")
    sync_outfits(state, [["a", False], ["b", False], ["c", False]])
    sync_outfits(state, [["a", False], ["c", False]])
    assert [o.prompt for o in state.outfits] == ["a", "c"]
    assert [o.id for o in state.outfits] == ["1", "2"]


def test_sync_props_preserves_shots_by_position() -> None:
    state = blank_state("Conan")
    set_props_enabled(state, True)
    sync_props(state, [["sword"], ["fire spell"]])
    assert [p.id for p in state.props] == ["1", "2"]
    state.props[0].shots = [PropShot(what="full blade", prompt="...", ref="refs/p.png")]
    sync_props(state, [["ancient sword"], ["fire spell"]])
    assert state.props[0].name == "ancient sword"
    assert state.props[0].shots[0].ref == "refs/p.png"
    assert prop_rows(state) == [["ancient sword"], ["fire spell"]]


def test_sync_props_drops_blank_rows() -> None:
    state = blank_state("Conan")
    sync_props(state, [["sword"], [""], [None]])
    assert [p.name for p in state.props] == ["sword"]


def test_saved_characters_lists_status(tmp_path: Path) -> None:
    ready = blank_state("Lucius")
    ready.current_step = None
    in_progress = blank_state("Conan")
    in_progress.current_step = "passport_face"
    save_state(ready, root=tmp_path)
    save_state(in_progress, root=tmp_path)

    rows = {row.name: row for row in saved_characters(root=tmp_path)}
    assert rows["Lucius"].status == "ready"
    assert rows["Lucius"].in_progress is False
    assert rows["Conan"].status == "in progress"
    assert rows["Conan"].in_progress is True


def test_saved_characters_skips_corrupt(tmp_path: Path) -> None:
    good = blank_state("Lucius")
    save_state(good, root=tmp_path)
    # A folder with state.json that is valid JSON but missing the required key.
    bad_dir = character_dir("broken", root=tmp_path)
    (bad_dir / "state.json").write_text("{}", encoding="utf-8")
    worse_dir = character_dir("garbage", root=tmp_path)
    (worse_dir / "state.json").write_text("{not json", encoding="utf-8")

    names = [row.name for row in saved_characters(root=tmp_path)]
    assert names == ["Lucius"]


def test_saved_characters_empty_bucket(tmp_path: Path) -> None:
    assert saved_characters(root=tmp_path) == []
