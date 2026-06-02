"""Gradio application factory for HF Spaces.

The wizard's logic lives in :mod:`create_char_passport.screens.handlers` (pure
session mutators) and :mod:`create_char_passport.screens.views` (rendering +
session->update glue). This module only assembles the screens into one
``gr.Blocks``, owns the per-session ``WizardSession`` state, and wires events
to those functions — no behaviour of its own, so the wiring stays lambda-free
and every referenced callable is unit-tested elsewhere.
"""

from __future__ import annotations

from functools import partial

import gradio as gr

from create_char_passport.gen import SceneId
from create_char_passport.screens import handlers
from create_char_passport.screens.router import SCREEN_ORDER, ScreenId, WizardSession
from create_char_passport.screens.views import (
    CHAR_DATA_REFRESH_KEYS,
    DATASET_REFRESH_KEYS,
    EMOTIONS_REFRESH_KEYS,
    FINISH_REFRESH_KEYS,
    OUTFITS_REFRESH_KEYS,
    PASSPORT_REFRESH_KEYS,
    PROPS_REFRESH_KEYS,
    ScreenHandle,
    build_screens,
    char_data_refresh,
    cost_banner_text,
    dataset_refresh,
    emotions_refresh,
    finish_refresh,
    home_refresh,
    interactive_update,
    outfits_refresh,
    passport_refresh,
    props_refresh,
    screen_visibility,
    update_table_fields,
)
from create_char_passport.state import CHARACTER_TABLE_KEYS
from create_char_passport.wizard import value_for_label


def _wire_home(home: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Extract-from-text and open-saved / open-extracted transitions."""
    c = home.components
    home_outputs = [c["notice"], c["extracted"], c["saved"]]
    c["extract_btn"].click(handlers.on_extract, [session, c["text"]], [session]).then(
        home_refresh, [session], home_outputs
    ).then(cost_banner_text, [session], [ctx.cost_banner])
    c["open_extracted_btn"].click(
        handlers.on_pick_extracted, [session, c["extracted"]], [session]
    ).then(char_data_refresh, [session], ctx.char_data_outputs).then(
        screen_visibility, [session], ctx.containers
    ).then(cost_banner_text, [session], [ctx.cost_banner])
    # A saved character can resume straight into the passport phase, so place the
    # cursor (honouring the need_regen gate) and repaint that form too.
    c["open_saved_btn"].click(handlers.on_open_saved, [session, c["saved"]], [session]).then(
        handlers.on_enter_passport, [session], [session]
    ).then(handlers.on_enter_emotions, [session], [session]).then(
        handlers.on_enter_outfits, [session], [session]
    ).then(handlers.on_enter_props, [session], [session]).then(
        handlers.on_enter_dataset, [session], [session]
    ).then(char_data_refresh, [session], ctx.char_data_outputs).then(
        passport_refresh, [session], ctx.passport_outputs
    ).then(emotions_refresh, [session], ctx.emotions_outputs).then(
        outfits_refresh, [session], ctx.outfits_outputs
    ).then(props_refresh, [session], ctx.props_outputs).then(
        dataset_refresh, [session], ctx.dataset_outputs
    ).then(finish_refresh, [session], ctx.finish_outputs).then(
        screen_visibility, [session], ctx.containers
    ).then(cost_banner_text, [session], [ctx.cost_banner])


def _wire_style(style: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Draft the style prompt and approve it (freezes STYLE, jumps to char-data)."""
    c = style.components
    c["draft_btn"].click(
        handlers.on_draft_style, [session, c["images"]], [session, c["style_text"]]
    ).then(cost_banner_text, [session], [ctx.cost_banner])
    c["approve_btn"].click(
        handlers.on_approve_style, [session, c["style_text"], c["images"]], [session]
    ).then(char_data_refresh, [session], ctx.char_data_outputs).then(
        screen_visibility, [session], ctx.containers
    ).then(cost_banner_text, [session], [ctx.cost_banner])


def _wire_char_data(char_data: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Trait-table edits + the four optional blocks + Next -> passport."""
    c = char_data.components
    table_fields = [c[f"table_{key}"] for key in CHARACTER_TABLE_KEYS]
    for field_box in table_fields:
        field_box.blur(update_table_fields, [session, *table_fields], [session])

    c["emotions_enabled"].change(
        handlers.on_toggle_emotions, [session, c["emotions_enabled"]], [session]
    ).then(interactive_update, [c["emotions_enabled"]], [c["emotion_table"]])

    base_emo_inputs = [session, c["base_emotion_enabled"], c["base_emotion_value"]]
    c["base_emotion_enabled"].change(
        handlers.on_update_base_emotion, base_emo_inputs, [session]
    ).then(interactive_update, [c["base_emotion_enabled"]], [c["base_emotion_value"]])
    c["base_emotion_value"].blur(handlers.on_update_base_emotion, base_emo_inputs, [session])
    c["base_emotion_preset"].change(
        value_for_label, [c["base_emotion_preset"]], [c["base_emotion_value"]]
    ).then(handlers.on_update_base_emotion, base_emo_inputs, [session])

    c["outfits_enabled"].change(
        handlers.on_toggle_outfits, [session, c["outfits_enabled"]], [session]
    ).then(interactive_update, [c["outfits_enabled"]], [c["outfit_table"]])
    c["outfit_table"].change(handlers.on_update_outfits, [session, c["outfit_table"]], [session])

    c["props_enabled"].change(
        handlers.on_toggle_props, [session, c["props_enabled"]], [session]
    ).then(interactive_update, [c["props_enabled"]], [c["prop_table"]])
    c["prop_table"].change(handlers.on_update_props, [session, c["prop_table"]], [session])

    c["next_btn"].click(handlers.on_next, [session], [session]).then(
        handlers.on_enter_passport, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(
        passport_refresh, [session], ctx.passport_outputs
    )


def _wire_passport(passport: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Generate / approve / regenerate + intra-phase back/forward for the 5 frames."""
    c = passport.components
    layer_inputs = [c["face_box"], c["body_box"], c["outfit_box"]]
    # Persist layer edits on blur (the handler writes only the editable layers).
    for box in layer_inputs:
        box.blur(handlers.on_passport_edit, [session, *layer_inputs], [session])

    # Generate / approve stay on the passport screen — repaint the form only.
    c["gen_btn"].click(handlers.on_passport_generate, [session, *layer_inputs], [session]).then(
        passport_refresh, [session], ctx.passport_outputs
    ).then(cost_banner_text, [session], [ctx.cost_banner])
    c["approve_btn"].click(handlers.on_passport_approve, [session], [session]).then(
        passport_refresh, [session], ctx.passport_outputs
    ).then(cost_banner_text, [session], [ctx.cost_banner])

    # Back can drop to char-data (frame 1); Forward can leave to the next phase —
    # both may change the visible screen, so toggle visibility + repaint neighbours.
    c["back_btn"].click(handlers.on_passport_back, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(char_data_refresh, [session], ctx.char_data_outputs).then(
        passport_refresh, [session], ctx.passport_outputs
    )
    # Forward off the last frame can leave to the emotions phase — place its cursor
    # and repaint that screen too.
    c["forward_btn"].click(handlers.on_passport_forward, [session], [session]).then(
        handlers.on_enter_emotions, [session], [session]
    ).then(handlers.on_enter_outfits, [session], [session]).then(
        handlers.on_enter_props, [session], [session]
    ).then(handlers.on_enter_dataset, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(passport_refresh, [session], ctx.passport_outputs).then(
        emotions_refresh, [session], ctx.emotions_outputs
    ).then(outfits_refresh, [session], ctx.outfits_outputs).then(
        props_refresh, [session], ctx.props_outputs
    ).then(dataset_refresh, [session], ctx.dataset_outputs)


def _wire_emotions(emotions: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Per-emotion point-wise generation + base-emotion block + approve/skip/back."""
    c = emotions.components
    # 3 point-wise emotion generators (index bound per button; handler is unit-tested).
    for i in range(3):
        c[f"emo_gen_{i}"].click(
            partial(handlers.on_emotion_generate, index=i), [session], [session]
        ).then(emotions_refresh, [session], ctx.emotions_outputs).then(
            cost_banner_text, [session], [ctx.cost_banner]
        )

    # Base-emotion block: toggle + value + preset sync back to the character data
    # (reuses the char-data base-emotion handler), then repaint to show/hide the block.
    base_inputs = [session, c["base_emotion_enabled"], c["base_emotion_value"]]
    c["base_emotion_enabled"].change(handlers.on_update_base_emotion, base_inputs, [session]).then(
        emotions_refresh, [session], ctx.emotions_outputs
    )
    c["base_emotion_value"].blur(handlers.on_update_base_emotion, base_inputs, [session])
    c["base_emotion_preset"].change(
        value_for_label, [c["base_emotion_preset"]], [c["base_emotion_value"]]
    ).then(handlers.on_update_base_emotion, base_inputs, [session])
    c["base_emotion_gen"].click(handlers.on_base_emotion_generate, [session], [session]).then(
        emotions_refresh, [session], ctx.emotions_outputs
    ).then(cost_banner_text, [session], [ctx.cost_banner])

    # Approve (offers skip on an incomplete set) / skip / back. Approve/skip can
    # land on the outfits phase — seed its cursor + repaint it too.
    c["approve_btn"].click(handlers.on_emotions_approve, [session], [session]).then(
        handlers.on_enter_outfits, [session], [session]
    ).then(handlers.on_enter_props, [session], [session]).then(
        handlers.on_enter_dataset, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(
        emotions_refresh, [session], ctx.emotions_outputs
    ).then(outfits_refresh, [session], ctx.outfits_outputs).then(
        props_refresh, [session], ctx.props_outputs
    ).then(dataset_refresh, [session], ctx.dataset_outputs)
    c["skip_btn"].click(handlers.on_emotions_skip, [session], [session]).then(
        handlers.on_enter_outfits, [session], [session]
    ).then(handlers.on_enter_props, [session], [session]).then(
        handlers.on_enter_dataset, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(
        emotions_refresh, [session], ctx.emotions_outputs
    ).then(outfits_refresh, [session], ctx.outfits_outputs).then(
        props_refresh, [session], ctx.props_outputs
    ).then(dataset_refresh, [session], ctx.dataset_outputs)
    c["back_btn"].click(handlers.on_emotions_back, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(passport_refresh, [session], ctx.passport_outputs).then(
        emotions_refresh, [session], ctx.emotions_outputs
    )


def _wire_outfits(outfits: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """One additional outfit at a time: clothing prompt + complex toggle, the 3
    full-length scene generators, costume details, and approve/back."""
    c = outfits.components
    out = ctx.outfits_outputs
    c["outfit_prompt"].blur(
        handlers.on_outfit_prompt_edit, [session, c["outfit_prompt"]], [session]
    )
    c["complex_toggle"].change(
        handlers.on_toggle_outfit_complex, [session, c["complex_toggle"]], [session]
    ).then(outfits_refresh, [session], out)

    scene_by_attr = {
        "front_full": SceneId.FRONT_FULL,
        "back_full": SceneId.BACK_FULL,
        "profile_full": SceneId.PROFILE_FULL,
    }
    for attr, scene in scene_by_attr.items():
        c[f"{attr}_gen"].click(
            partial(handlers.on_outfit_scene_generate, scene_id=scene), [session], [session]
        ).then(outfits_refresh, [session], out).then(cost_banner_text, [session], [ctx.cost_banner])
        c[f"{attr}_approved"].change(
            partial(handlers.on_outfit_scene_approve_toggle, scene_id=scene),
            [session, c[f"{attr}_approved"]],
            [session],
        )

    for j in range(3):
        c[f"detail_prompt_{j}"].blur(
            partial(handlers.on_outfit_detail_prompt_edit, j=j),
            [session, c[f"detail_prompt_{j}"]],
            [session],
        )
        c[f"detail_gen_{j}"].click(
            partial(handlers.on_outfit_detail_generate, j=j), [session], [session]
        ).then(outfits_refresh, [session], out).then(cost_banner_text, [session], [ctx.cost_banner])
        c[f"detail_delete_{j}"].click(
            partial(handlers.on_outfit_delete_detail, j=j), [session], [session]
        ).then(outfits_refresh, [session], out)
        c[f"detail_delete_confirm_{j}"].click(
            partial(handlers.on_outfit_delete_detail_confirmed, j=j), [session], [session]
        ).then(outfits_refresh, [session], out)
    c["add_detail_btn"].click(handlers.on_outfit_add_detail, [session], [session]).then(
        outfits_refresh, [session], out
    )

    # Approve advances to the next outfit or out of the phase (→ props / dataset).
    c["approve_btn"].click(handlers.on_approve_outfit, [session], [session]).then(
        handlers.on_enter_props, [session], [session]
    ).then(handlers.on_enter_dataset, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(outfits_refresh, [session], out).then(props_refresh, [session], ctx.props_outputs).then(
        dataset_refresh, [session], ctx.dataset_outputs
    )
    c["back_btn"].click(handlers.on_outfits_back, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(emotions_refresh, [session], ctx.emotions_outputs).then(
        passport_refresh, [session], ctx.passport_outputs
    ).then(outfits_refresh, [session], out)


def _wire_props(props: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """One prop at a time: 1..3 product shots (what + prompt + generate/delete) + nav."""
    c = props.components
    out = ctx.props_outputs
    for j in range(3):
        c[f"shot_what_{j}"].blur(
            partial(handlers.on_prop_shot_what_edit, j=j), [session, c[f"shot_what_{j}"]], [session]
        )
        c[f"shot_prompt_{j}"].blur(
            partial(handlers.on_prop_shot_prompt_edit, j=j),
            [session, c[f"shot_prompt_{j}"]],
            [session],
        )
        c[f"shot_gen_{j}"].click(
            partial(handlers.on_prop_shot_generate, j=j), [session], [session]
        ).then(props_refresh, [session], out).then(cost_banner_text, [session], [ctx.cost_banner])
        c[f"shot_delete_{j}"].click(
            partial(handlers.on_prop_delete_shot, j=j), [session], [session]
        ).then(props_refresh, [session], out)
        c[f"shot_delete_confirm_{j}"].click(
            partial(handlers.on_prop_delete_shot_confirmed, j=j), [session], [session]
        ).then(props_refresh, [session], out)
    c["add_shot_btn"].click(handlers.on_prop_add_shot, [session], [session]).then(
        props_refresh, [session], out
    )
    c["forward_btn"].click(handlers.on_props_forward, [session], [session]).then(
        handlers.on_enter_dataset, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(props_refresh, [session], out).then(
        dataset_refresh, [session], ctx.dataset_outputs
    )
    # Back to the previous prop, or out to outfits — re-seed the outfit cursor
    # (mirrors the forward chains) so the landing OUTFITS screen is usable.
    c["back_btn"].click(handlers.on_props_back, [session], [session]).then(
        handlers.on_enter_outfits, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(
        outfits_refresh, [session], ctx.outfits_outputs
    ).then(props_refresh, [session], out)


def _wire_dataset(dataset: ScreenHandle, session: gr.State, ctx: _Ctx) -> None:
    """Dataset: per-composition generate / approve(→archive) / add / back + finish."""
    c = dataset.components
    out = ctx.dataset_outputs
    c["composition_prompt"].blur(
        handlers.on_dataset_prompt_edit, [session, c["composition_prompt"]], [session]
    )
    c["gen_btn"].click(handlers.on_dataset_generate, [session], [session]).then(
        dataset_refresh, [session], out
    ).then(cost_banner_text, [session], [ctx.cost_banner])
    # Approve archives the frame and advances — the last one finishes (→ FINISH).
    c["approve_btn"].click(handlers.on_dataset_approve, [session], [session]).then(
        screen_visibility, [session], ctx.containers
    ).then(dataset_refresh, [session], out).then(finish_refresh, [session], ctx.finish_outputs)
    c["add_composition_btn"].click(
        handlers.on_dataset_add_composition, [session, c["new_composition"]], [session]
    ).then(dataset_refresh, [session], out)
    c["back_btn"].click(handlers.on_dataset_back, [session], [session]).then(
        handlers.on_enter_props, [session], [session]
    ).then(screen_visibility, [session], ctx.containers).then(
        props_refresh, [session], ctx.props_outputs
    ).then(dataset_refresh, [session], out)


def _wire_finish(finish: ScreenHandle, session: gr.State) -> None:
    """LoRA-ready export — zip approved/ into an img + caption bundle for download."""
    c = finish.components
    c["export_btn"].click(handlers.on_export_lora, [session], [c["export_file"], c["export_note"]])


class _Ctx:
    """Shared component references the per-screen wiring helpers need."""

    def __init__(self, handles: dict[ScreenId, ScreenHandle], cost_banner: gr.Markdown) -> None:
        self.containers = [handles[screen].container for screen in SCREEN_ORDER]
        cd = handles[ScreenId.CHAR_DATA].components
        self.char_data_outputs = [cd[key] for key in CHAR_DATA_REFRESH_KEYS]
        pp = handles[ScreenId.PASSPORT].components
        self.passport_outputs = [pp[key] for key in PASSPORT_REFRESH_KEYS]
        em = handles[ScreenId.EMOTIONS].components
        self.emotions_outputs = [em[key] for key in EMOTIONS_REFRESH_KEYS]
        of = handles[ScreenId.OUTFITS].components
        self.outfits_outputs = [of[key] for key in OUTFITS_REFRESH_KEYS]
        pr = handles[ScreenId.PROPS].components
        self.props_outputs = [pr[key] for key in PROPS_REFRESH_KEYS]
        ds = handles[ScreenId.DATASET].components
        self.dataset_outputs = [ds[key] for key in DATASET_REFRESH_KEYS]
        fn = handles[ScreenId.FINISH].components
        self.finish_outputs = [fn[key] for key in FINISH_REFRESH_KEYS]
        self.cost_banner = cost_banner


def build_demo() -> gr.Blocks:
    """Return the wizard's ``gr.Blocks`` demo.

    Screens are rendered once and stay mounted; only their ``visible``
    attribute is toggled, which keeps the ``gr.State`` + back/forward gates
    simple. Each session gets its own :class:`WizardSession` instance.
    """
    with gr.Blocks(title="Create Char Passport") as demo:
        gr.Markdown("# Create Char Passport")
        # Global running-cost banner, visible on every screen (lives outside the
        # per-screen groups). Refreshed after each cost- or character-changing event.
        cost_banner = gr.Markdown(cost_banner_text(WizardSession()))
        session = gr.State(WizardSession())
        handles = build_screens()
        if set(handles.keys()) != set(SCREEN_ORDER):
            missing = set(SCREEN_ORDER) - set(handles.keys())
            msg = f"screens missing from build_screens(): {sorted(s.value for s in missing)}"
            raise RuntimeError(msg)

        ctx = _Ctx(handles, cost_banner)
        home = handles[ScreenId.HOME]
        _wire_home(home, session, ctx)
        _wire_style(handles[ScreenId.STYLE], session, ctx)
        _wire_char_data(handles[ScreenId.CHAR_DATA], session, ctx)
        _wire_passport(handles[ScreenId.PASSPORT], session, ctx)
        _wire_emotions(handles[ScreenId.EMOTIONS], session, ctx)
        _wire_outfits(handles[ScreenId.OUTFITS], session, ctx)
        _wire_props(handles[ScreenId.PROPS], session, ctx)
        _wire_dataset(handles[ScreenId.DATASET], session, ctx)
        _wire_finish(handles[ScreenId.FINISH], session)

        # Populate the saved-characters list + cost banner from the bucket on app
        # open, so a returning user sees their characters without a paid call.
        demo.load(
            home_refresh,
            [session],
            [home.components["notice"], home.components["extracted"], home.components["saved"]],
        ).then(cost_banner_text, [session], [cost_banner])
    return demo
