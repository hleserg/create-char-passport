"""UI hooks for the AI-assist buttons — contract K4.

Foundation work only provides the *slot* abstraction (the empty container
the wizard puts next to each prompt field). Task 6 of the epic fills the
slots with the actual `Check with AI` / `Edit with AI` logic.
"""

from create_char_passport.ai.slots import (
    AIEditSlot,
    AISlot,
    AISlotKind,
    SlotContext,
    build_ai_check_slot,
    build_ai_edit_slot,
)

__all__ = [
    "AIEditSlot",
    "AISlot",
    "AISlotKind",
    "SlotContext",
    "build_ai_check_slot",
    "build_ai_edit_slot",
]
