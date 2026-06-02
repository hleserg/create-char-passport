"""K4 slot wiring — fills the reserved AI-assist containers (HLE-731).

Dumb Gradio glue only: it re-enters each reserved slot container (rendered empty
by :mod:`create_char_passport.ai.slots`), adds the "Проверить с ИИ" button and an
inline result panel, and wires the clicks to the pure session handlers. Every
decision (resolve the real step key under the cursor, the paid call + billing,
the write-back) lives in tested handlers; this module only maps a
:class:`~create_char_passport.ai.review.CheckOutcome` to ``gr.update`` and
delegates. Wiring stays lambda-free (module-level callables + ``partial``) so the
glue functions are unit-testable.
"""

from __future__ import annotations

from functools import partial
from typing import Any

import gradio as gr

from create_char_passport.ai.review import CheckOutcome
from create_char_passport.ai.slots import AISlot
from create_char_passport.screens import handlers
from create_char_passport.screens.views import cost_banner_text


def check_result_updates(outcome: CheckOutcome | None) -> list[Any]:
    """Map a check outcome to updates for ``[result_md, proposed_box, accept, reject]``.

    ``None`` (nothing generated to check yet) shows a hint with no prompt offered;
    an outcome with no ``new_prompt`` shows only the justification; an outcome with
    a proposed prompt reveals the editable box + the Accept button.
    """
    if outcome is None:
        return [
            gr.update(value="_Сначала сгенерируй кадр для проверки._", visible=True),
            gr.update(value="", visible=False),
            gr.update(visible=False),
            gr.update(visible=True),
        ]
    has_new = outcome.new_prompt is not None
    return [
        gr.update(value=f"**Проверка ИИ:** {outcome.justification}", visible=True),
        gr.update(value=outcome.new_prompt or "", visible=has_new),
        gr.update(visible=has_new),
        gr.update(visible=True),
    ]


def hidden_panel() -> list[Any]:
    """Collapse the result panel's four components."""
    return [gr.update(visible=False) for _ in range(4)]


def _on_check(step_key: str, index: int | None, session: Any) -> tuple[Any, ...]:
    outcome = handlers.run_ai_check(session, step_key, index)
    return (session, *check_result_updates(outcome), cost_banner_text(session))


def _on_accept(step_key: str, index: int | None, session: Any, new_prompt: str) -> Any:
    return handlers.accept_ai_check(session, step_key, index, new_prompt)


def wire_check_slot(
    slot: AISlot,
    *,
    session: gr.State,
    cost_banner: gr.Markdown,
    refresh_fn: Any,
    refresh_outputs: list[Any],
    index: int | None = None,
) -> None:
    """Fill one "Check with AI" slot: button + result panel + click wiring.

    Accepting writes the prompt into state (via the handler) then re-runs the
    screen ``refresh_fn`` — which repaints the step's prompt field from state —
    so the edit is reflected without poking the component directly.
    """
    ctx = slot.context
    with ctx.container:
        check_btn = gr.Button("Проверить с ИИ (платно)", size="sm")
        result = gr.Markdown(visible=False)
        proposed = gr.Textbox(
            label="Предложенный ИИ промт", lines=2, visible=False, interactive=True
        )
        with gr.Row():
            accept = gr.Button("Принять", variant="primary", size="sm", visible=False)
            reject = gr.Button("Отклонить", size="sm", visible=False)
    panel = [result, proposed, accept, reject]
    check_btn.click(
        partial(_on_check, ctx.step_key, index), [session], [session, *panel, cost_banner]
    )
    accept.click(partial(_on_accept, ctx.step_key, index), [session, proposed], [session]).then(
        refresh_fn, [session], refresh_outputs
    ).then(hidden_panel, None, panel)
    reject.click(hidden_panel, None, panel)
