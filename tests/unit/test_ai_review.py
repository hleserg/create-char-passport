"""Tests for the AI-assist review core (HLE-731) — parser + check/edit + write-back."""

from __future__ import annotations

from create_char_passport.ai.review import (
    NO_CHANGES,
    NO_RESPONSE,
    UNEXPECTED,
    CheckOutcome,
    EditOutcome,
    apply_step_prompt,
    check_step,
    edit_character,
    editable_step_keys,
    parse_check_reply,
    parse_edit_reply,
)
from create_char_passport.state import (
    OutfitDetail,
    OutfitEntry,
    PropEntry,
    PropShot,
    blank_state,
)


class _Call:
    """Scripted LLM stub: returns replies in order, records every prompt seen."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.prompts: list[str] = []

    def __call__(self, prompt, image_b64=None, *, images_b64=None, model=None, meter=None):
        self.prompts.append(prompt)
        idx = len(self.prompts) - 1
        return self.replies[idx] if idx < len(self.replies) else self.replies[-1]


# --------------------------------------------------------------------------- #
# Parsers
# --------------------------------------------------------------------------- #
def test_parse_check_reply_well_formed() -> None:
    assert parse_check_reply("{обоснование тут}[a new prompt]") == (
        "обоснование тут",
        "a new prompt",
    )


def test_parse_check_reply_empty_bracket_is_no_prompt() -> None:
    assert parse_check_reply("{всё ок}[]") == ("всё ок", None)


def test_parse_check_reply_missing_braces() -> None:
    assert parse_check_reply("just freeform text") == (None, None)


def test_parse_edit_reply_filters_unknown_and_empty() -> None:
    text = (
        "&passport_face&{уточни челюсть}[strong jaw, blue eyes]"
        "&dataset_0&{поза}[full body, running]"
        "&bogus_step&{нет такого}[should be ignored]"
        "&passport_body&{пусто}[]"
    )
    blocks = parse_edit_reply(text, {"passport_face", "passport_body", "dataset_0"})
    keys = [b.step_key for b in blocks]
    assert keys == ["passport_face", "dataset_0"]  # bogus dropped, empty-prompt dropped
    assert blocks[0].new_prompt == "strong jaw, blue eyes"
    assert blocks[0].justification == "уточни челюсть"


def test_parse_edit_reply_no_markers() -> None:
    assert parse_edit_reply("everything looks fine", {"passport_face"}) == []


def test_parse_check_reply_bracket_inside_justification() -> None:
    # A "[...]" inside the {justification} prose must not be taken as the prompt.
    just, prompt = parse_check_reply("{добавь [шрам] на щеку}[rugged face, scar on cheek]")
    assert just == "добавь [шрам] на щеку"
    assert prompt == "rugged face, scar on cheek"


def test_parse_edit_reply_ampersand_in_prompt() -> None:
    # A literal "&" inside a proposed prompt must not break block delimiting.
    text = "&passport_face&{ч/б}[black & white face]&dataset_0&{поза}[full body, running]"
    blocks = parse_edit_reply(text, {"passport_face", "dataset_0"})
    assert [b.step_key for b in blocks] == ["passport_face", "dataset_0"]
    assert blocks[0].new_prompt == "black & white face"


# --------------------------------------------------------------------------- #
# check_step
# --------------------------------------------------------------------------- #
def test_check_step_well_formed() -> None:
    call = _Call("{лицо чистое, но добавь шрам}[rugged face, scar on cheek]")
    out = check_step(blank_state("Conan"), "passport_face", call=call)
    assert isinstance(out, CheckOutcome)
    assert out.new_prompt == "rugged face, scar on cheek"
    assert out.justification == "лицо чистое, но добавь шрам"
    assert out.ok is True
    assert len(call.prompts) == 1  # well-formed → no retry


def test_check_step_no_change() -> None:
    call = _Call("{выглядит хорошо}[]")
    out = check_step(blank_state("Conan"), "base_emotion", call=call)
    assert out.new_prompt is None  # empty bracket → field untouched
    assert out.justification == "выглядит хорошо"


def test_check_step_api_down() -> None:
    call = _Call("")  # call_llm returns "" on API failure
    out = check_step(blank_state("Conan"), "passport_face", call=call)
    assert out.ok is False
    assert out.justification == NO_RESPONSE
    assert out.new_prompt is None
    assert len(call.prompts) == 1  # no retry — a down API won't recover


def test_check_step_malformed_then_recovers() -> None:
    call = _Call("garbage with no braces", "{ок}[fixed prompt]")
    out = check_step(blank_state("Conan"), "passport_face", call=call)
    assert len(call.prompts) == 2  # one reminder retry
    assert out.new_prompt == "fixed prompt"


def test_check_step_malformed_twice() -> None:
    call = _Call("still no braces", "again no braces")
    out = check_step(blank_state("Conan"), "passport_face", call=call)
    assert len(call.prompts) == 2
    assert out.justification == UNEXPECTED
    assert out.new_prompt is None


# --------------------------------------------------------------------------- #
# edit_character
# --------------------------------------------------------------------------- #
def _edit_ready():
    state = blank_state("Conan")
    state.outfits_enabled = True
    state.outfits.append(OutfitEntry(id="1", prompt="leather armor"))
    state.dataset_compositions = ["walking"]
    return state


def test_edit_character_parses_blocks_and_filters() -> None:
    state = _edit_ready()
    call = _Call(
        "&passport_face&{сильнее челюсть}[strong jaw]"
        "&dataset_0&{динамичнее}[full body, mid-leap]"
        "&emotion_angry&{левый шаг}[should be ignored]"
    )
    out = edit_character(state, "сделай его суровее", call=call)
    assert isinstance(out, EditOutcome)
    keys = [b.step_key for b in out.blocks]
    assert keys == ["passport_face", "dataset_0"]  # emotion_* not a valid edit key
    assert len(call.prompts) == 1


def test_edit_character_no_changes_prose() -> None:
    call = _Call("Всё выглядит согласованно, правок не нужно.", "Всё ок.")
    out = edit_character(_edit_ready(), "проверь всё", call=call)
    assert out.blocks == []
    assert out.note  # carries the model's prose, not a crash
    assert len(call.prompts) == 2  # no markers → one reminder retry


def test_edit_character_api_down() -> None:
    out = edit_character(_edit_ready(), "проверь", call=_Call(""))
    assert out.ok is False
    assert out.note == NO_RESPONSE


def test_edit_character_empty_reply_note_falls_back() -> None:
    # A reply with no markers and no usable prose still yields the friendly note.
    out = edit_character(_edit_ready(), "проверь", call=_Call("   ", "   "))
    assert out.blocks == []
    assert out.note in (NO_CHANGES, NO_RESPONSE)


# --------------------------------------------------------------------------- #
# editable_step_keys
# --------------------------------------------------------------------------- #
def test_editable_step_keys() -> None:
    state = blank_state("Conan")
    state.dataset_compositions = ["a", "b"]
    assert editable_step_keys(state) == ["passport_face", "passport_body", "dataset_0", "dataset_1"]
    state.outfits_enabled = True
    state.outfits.append(OutfitEntry(id="1"))
    state.outfits.append(OutfitEntry(id="2"))
    assert editable_step_keys(state) == [
        "passport_face",
        "passport_body",
        "outfit_1",
        "outfit_2",
        "dataset_0",
        "dataset_1",
    ]


# --------------------------------------------------------------------------- #
# apply_step_prompt — routes through each phase's setter
# --------------------------------------------------------------------------- #
def test_apply_step_prompt_passport_face_and_body() -> None:
    state = blank_state("Conan")
    assert apply_step_prompt(state, "passport_face", "  rugged face  ") is True
    assert state.prompt_layers.face == "rugged face"
    assert apply_step_prompt(state, "passport_body", "tall, muscular") is True
    assert state.prompt_layers.body == "tall, muscular"


def test_apply_step_prompt_base_emotion_preserves_enabled() -> None:
    state = blank_state("Conan")
    state.emotions.base_emotion.enabled = True
    assert apply_step_prompt(state, "base_emotion", "stern") is True
    assert state.emotions.base_emotion.value == "stern"
    assert state.emotions.base_emotion.enabled is True


def test_apply_step_prompt_outfit_and_detail() -> None:
    state = blank_state("Conan")
    state.outfits.append(OutfitEntry(id="1", prompt="old", details=[OutfitDetail(prompt="old d")]))
    assert apply_step_prompt(state, "outfit_1", "battered plate armor") is True
    assert state.outfits[0].prompt == "battered plate armor"
    assert apply_step_prompt(state, "outfit_1_detail_1", "ornate buckle") is True
    assert state.outfits[0].details[0].prompt == "ornate buckle"


def test_apply_step_prompt_prop_and_dataset() -> None:
    state = blank_state("Conan")
    state.props.append(PropEntry(id="1", shots=[PropShot(prompt="old")]))
    state.dataset_compositions = ["old pose"]
    assert apply_step_prompt(state, "prop_1_shot_1", "a glowing sword") is True
    assert state.props[0].shots[0].prompt == "a glowing sword"
    assert apply_step_prompt(state, "dataset_0", "full body, crouching") is True
    assert state.dataset_compositions[0] == "full body, crouching"


def test_apply_step_prompt_frozen_passport_frame_returns_false() -> None:
    # A frozen passport frame (profile/back/3q) has no editable layer → a true
    # no-op, reported as False (not a phantom write that clobbers FACE).
    state = blank_state("Conan")
    state.prompt_layers.face = "original identity"
    assert apply_step_prompt(state, "passport_profile", "should not write") is False
    assert state.prompt_layers.face == "original identity"
    # FACE/BODY frames still write and report True.
    assert apply_step_prompt(state, "passport_face", "rugged jaw") is True
    assert state.prompt_layers.face == "rugged jaw"


def test_apply_step_prompt_emotion_series_is_noop() -> None:
    # Rewriting an emotion label would re-key the step — refuse it.
    state = blank_state("Conan")
    assert apply_step_prompt(state, "emotion_angry", "furious") is False


def test_apply_step_prompt_unknown_outfit_or_prop_is_noop() -> None:
    # A marker for a step that does not exist must never create a phantom entry.
    state = blank_state("Conan")
    state.outfits.append(OutfitEntry(id="1", prompt="armor"))
    state.props.append(PropEntry(id="1", shots=[PropShot(prompt="sword")]))
    assert apply_step_prompt(state, "outfit_99", "x") is False
    assert apply_step_prompt(state, "outfit_1_detail_5", "x") is False
    assert apply_step_prompt(state, "prop_9_shot_1", "x") is False
    assert state.outfits[0].prompt == "armor"  # untouched
    assert state.props[0].shots[0].prompt == "sword"
