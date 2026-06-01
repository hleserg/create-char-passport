"""Base-emotion presets (§5 — "Список пресетов").

The character-data screen offers a "…" button next to the base-emotion field
that drops a list of 12 ready expressions. Each preset is the English value
written into ``[EXPRESSION]`` plus a Russian description shown to the user.
The value is what matters downstream; the description is purely a UI hint.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EmotionPreset:
    """One base-emotion preset — the prompt value and its Russian gloss."""

    value: str
    description: str

    @property
    def label(self) -> str:
        """Dropdown label combining value and description."""
        return f"{self.value} — {self.description}"


BASE_EMOTION_PRESETS: tuple[EmotionPreset, ...] = (
    EmotionPreset(
        "calm, composed", "Спокойный, собранный — невозмутимое, нейтрально-уверенное лицо"
    ),
    EmotionPreset(
        "grim, brooding", "Мрачный, угрюмый — тяжёлый взгляд, сведённые брови (без открытой злости)"
    ),
    EmotionPreset("stern, serious", "Суровый, серьёзный — жёсткое сосредоточенное лицо, без тепла"),
    EmotionPreset(
        "confident, slight smirk",
        "Уверенный, с лёгкой ухмылкой — спокойная насмешка, превосходство",
    ),
    EmotionPreset("warm, friendly", "Тёплый, дружелюбный — мягкое открытое лицо"),
    EmotionPreset("tired, weary", "Усталый, измотанный — опущенные веки, тяжесть в лице"),
    EmotionPreset("cold, detached", "Холодный, отстранённый — бесстрастность, дистанция, «маска»"),
    EmotionPreset("cunning, sly", "Хитрый, лукавый — прищур, едва заметная усмешка, расчёт"),
    EmotionPreset(
        "melancholic, sad", "Меланхоличный, печальный — тихая грусть фоном, опущенный взгляд"
    ),
    EmotionPreset(
        "arrogant, haughty", "Надменный, высокомерный — приподнятый подбородок, взгляд свысока"
    ),
    EmotionPreset("anxious, wary", "Тревожный, настороженный — напряжение, насторожённый взгляд"),
    EmotionPreset("kind, gentle", "Добрый, мягкий — спокойная теплота, незлобивое лицо"),
)

_BY_LABEL: dict[str, str] = {preset.label: preset.value for preset in BASE_EMOTION_PRESETS}


def preset_labels() -> list[str]:
    """All preset dropdown labels, in canonical order."""
    return [preset.label for preset in BASE_EMOTION_PRESETS]


def value_for_label(label: str) -> str:
    """Map a chosen dropdown label back to its ``[EXPRESSION]`` value.

    Unknown labels pass through unchanged so a free-typed value still works.
    """
    return _BY_LABEL.get(label, label)
