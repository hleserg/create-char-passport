"""K4 — empty Gradio containers reserved for the AI-assist buttons.

Each step-generation screen renders an ``ai_check_slot`` next to its prompt
field; passport + dataset additionally render an ``ai_edit_slot``. Task 6
of the epic populates the slots with "Check with AI" / "Edit with AI"
logic without having to rewrite the screens (the slots are reserved here).

Contract handed to task 6:

* ``step_key`` — the wizard step the slot belongs to (drives the check-list).
* ``prompt_field`` — the Gradio component holding the editable prompt text;
  task 6 writes ``[новый промт]`` back into this component.
* ``container`` — a ``gr.Group`` task 6 fills with its own components.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import gradio as gr


class AISlotKind(StrEnum):
    """Which assist button the slot is reserved for."""

    CHECK = "check"
    EDIT = "edit"


@dataclass(slots=True)
class SlotContext:
    """Everything task 6 needs to wire its callback for one slot."""

    step_key: str
    prompt_field: gr.Component
    container: gr.Group


@dataclass(slots=True)
class AISlot:
    """Slot reserved for the "Check with AI" button."""

    kind: AISlotKind
    context: SlotContext


@dataclass(slots=True)
class AIEditSlot:
    """Slot reserved for the global "Edit with AI" button (passport + dataset)."""

    kind: AISlotKind
    context: SlotContext


def _build_slot(
    step_key: str,
    prompt_field: gr.Component,
    *,
    label: str,
    elem_id_prefix: str,
) -> tuple[gr.Group, Any]:
    """Render the empty container that :mod:`create_char_passport.ai.wiring` fills.

    The group starts empty (``ai.wiring.wire_check_slot`` re-enters it to add the
    button + result panel); ``label`` is kept only for the elem-id namespace.
    """
    safe_key = step_key.replace(":", "_")
    with gr.Group(elem_id=f"{elem_id_prefix}-{safe_key}") as container:
        pass
    _ = (prompt_field, label)  # prompt_field is captured by the dataclass for wiring
    return container, None


def build_ai_check_slot(step_key: str, prompt_field: gr.Component) -> AISlot:
    """Render and return the per-step "Check with AI" slot."""
    container, _ = _build_slot(
        step_key,
        prompt_field,
        label="Check with AI",
        elem_id_prefix="ai-check-slot",
    )
    return AISlot(
        kind=AISlotKind.CHECK,
        context=SlotContext(
            step_key=step_key,
            prompt_field=prompt_field,
            container=container,
        ),
    )


def build_ai_edit_slot(step_key: str, prompt_field: gr.Component) -> AIEditSlot:
    """Render the global "Edit with AI" slot (passport + dataset only)."""
    container, _ = _build_slot(
        step_key,
        prompt_field,
        label="Edit with AI (whole character review)",
        elem_id_prefix="ai-edit-slot",
    )
    return AIEditSlot(
        kind=AISlotKind.EDIT,
        context=SlotContext(
            step_key=step_key,
            prompt_field=prompt_field,
            container=container,
        ),
    )
