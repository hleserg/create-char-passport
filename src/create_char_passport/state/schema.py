"""Typed character-state schema — mirrors ``state.json`` (§6 of the plan).

The schema is a tree of ``dataclass(slots=True)`` nodes so the runtime
state object is mutable, type-checked, and trivially (de)serializable. We
deliberately avoid pydantic here: state.json is an *internal* file we own
end-to-end, and dataclasses keep round-tripping cheap and tooling-friendly.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

_DEFAULT_EMOTIONS: tuple[tuple[str, str], ...] = (
    ("neutral", "neutral"),
    ("angry, furious", "angry, furious"),
    ("smiling warmly", "smiling warmly"),
)

_NAME_SLUG_RE = re.compile(r"[^a-z0-9]+")


def character_id_from_name(name: str) -> str:
    """Deterministic kebab-case id for a character name.

    Empty / whitespace-only names collapse to ``"character"`` so we always
    have a usable folder name; the canonical id is whatever ends up in
    ``CharacterState.character_id``.
    """
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = _NAME_SLUG_RE.sub("-", normalized.lower()).strip("-")
    return slug or "character"


@dataclass(slots=True)
class PromptLayers:
    """Six-layer prompt — order is canonical, missing layers are empty strings."""

    style: str = ""
    face: str = ""
    body: str = ""
    outfit: str = ""
    expression: str = ""
    composition: str = ""


@dataclass(slots=True)
class EmotionItem:
    """One row of the (optional) emotions series."""

    value: str
    ref: str | None = None


@dataclass(slots=True)
class BaseEmotion:
    """Optional "default expression" of the character.

    Even when ``enabled`` is False, downstream phases treat the effective
    value as ``"neutral"`` (see contract K3).
    """

    enabled: bool = False
    value: str = ""
    ref: str | None = None


@dataclass(slots=True)
class Emotions:
    """Optional emotion block (the 3 base emotions + base emotion handle)."""

    enabled: bool = False
    items: list[EmotionItem] = field(
        default_factory=lambda: [EmotionItem(value=v, ref=None) for _, v in _DEFAULT_EMOTIONS]
    )
    base_emotion: BaseEmotion = field(default_factory=BaseEmotion)


@dataclass(slots=True)
class BaseOutfit:
    """Base outfit — property of the character, NOT inside ``outfits[]``."""

    prompt: str = ""
    frozen: bool = False
    ref: str | None = None


@dataclass(slots=True)
class OutfitRefs:
    """Approved outfit references by scene. Optional fields stay ``None``."""

    front_full: str | None = None
    back_full: str | None = None
    profile_full: str | None = None


@dataclass(slots=True)
class OutfitDetail:
    """A close-up shot tied to a complex outfit."""

    prompt: str = ""
    ref: str | None = None


@dataclass(slots=True)
class OutfitEntry:
    """One *additional* outfit (base outfit is on ``CharacterState.base_outfit``)."""

    id: str
    prompt: str = ""
    complex: bool = False
    refs: OutfitRefs = field(default_factory=OutfitRefs)
    details: list[OutfitDetail] = field(default_factory=list)


@dataclass(slots=True)
class PropShot:
    """One frame of a prop / magic effect (1..3 per prop)."""

    what: str = ""
    prompt: str = ""
    ref: str | None = None


@dataclass(slots=True)
class PropEntry:
    """A prop / piece of magic the character carries (any count)."""

    id: str
    name: str = ""
    shots: list[PropShot] = field(default_factory=list)


@dataclass(slots=True)
class StepRecord:
    """Per-step snapshot saved into ``state.steps{}``."""

    last_path: str | None = None
    approved_path: str | None = None
    prompt_layers: PromptLayers = field(default_factory=PromptLayers)
    need_regen: bool = False
    # Soft cascade flag (passport §5): raised on a later, already-approved frame
    # when an identity-reference frame (FACE/BODY) is regenerated, so the UI can
    # warn "the base shifted — re-check this one". Distinct from ``need_regen``:
    # advisory only (the user decides), never forces a jump-back. Cleared when
    # this frame is itself regenerated or (re)approved.
    stale: bool = False


@dataclass(slots=True)
class CostLedger:
    """Running API spend, in USD, split by call type (§7 "Стоимость").

    Persisted on the character so the figure survives reopening a saved
    character; an in-memory copy on the session aggregates the whole run
    (including pre-character calls like extraction). Costs are list-price
    estimates — see ``create_char_passport.gen.pricing``.
    """

    image_usd: float = 0.0
    llm_usd: float = 0.0
    image_calls: int = 0
    llm_calls: int = 0
    # True once any call used an approximate / unknown list price, so the UI
    # can honestly mark the total as an estimate ("≈") only when it really is.
    has_estimate: bool = False

    @property
    def total_usd(self) -> float:
        """Combined image + LLM spend."""
        return self.image_usd + self.llm_usd

    def merge(self, other: CostLedger) -> None:
        """Fold another ledger's totals (a single action's spend) into this one."""
        self.image_usd += other.image_usd
        self.llm_usd += other.llm_usd
        self.image_calls += other.image_calls
        self.llm_calls += other.llm_calls
        self.has_estimate = self.has_estimate or other.has_estimate


@dataclass(slots=True)
class CharacterState:
    """Root of ``state.json`` — full §6 schema."""

    character_id: str
    name: str = ""
    character_table: dict[str, Any] = field(default_factory=dict)
    emotions: Emotions = field(default_factory=Emotions)
    base_outfit: BaseOutfit = field(default_factory=BaseOutfit)
    outfits: list[OutfitEntry] = field(default_factory=list)
    outfits_enabled: bool = False
    active_outfit_id: str = "base"
    props_enabled: bool = False
    props: list[PropEntry] = field(default_factory=list)
    prompt_layers: PromptLayers = field(default_factory=PromptLayers)
    # Project STYLE reference *image* (relative path, e.g. ``refs/style.png``).
    # Complements the frozen ``prompt_layers.style`` text: attached with role
    # ``style`` to every generation so the model copies the manner, not content.
    style_ref: str | None = None
    steps: dict[str, StepRecord] = field(default_factory=dict)
    current_step: str | None = None
    dataset_compositions: list[str] = field(default_factory=list)
    # Per-character COMPOSITION overrides: ``scene_id -> custom prompt``. An
    # entry replaces the hardcoded scene preset for every future generation of
    # that scene (see ``create_char_passport.gen.scenes``). Empty by default.
    scene_overrides: dict[str, str] = field(default_factory=dict)
    # Running API spend attributed to this character (image-gen + LLM).
    cost: CostLedger = field(default_factory=CostLedger)


def blank_state(name: str, character_id: str | None = None) -> CharacterState:
    """Fresh state for a newly-extracted character."""
    cid = character_id or character_id_from_name(name)
    return CharacterState(character_id=cid, name=name)


def state_to_dict(state: CharacterState) -> dict[str, Any]:
    """Serialize to a JSON-ready dict (drops dataclass metadata)."""
    return asdict(state)


def _prompt_layers(data: dict[str, Any] | None) -> PromptLayers:
    if not data:
        return PromptLayers()
    return PromptLayers(
        style=data.get("style", ""),
        face=data.get("face", ""),
        body=data.get("body", ""),
        outfit=data.get("outfit", ""),
        expression=data.get("expression", ""),
        composition=data.get("composition", ""),
    )


def _emotions(data: dict[str, Any] | None) -> Emotions:
    if not data:
        return Emotions()
    items_data = data.get("items") or [{"value": v, "ref": None} for _, v in _DEFAULT_EMOTIONS]
    base_data = data.get("base_emotion") or {}
    return Emotions(
        enabled=bool(data.get("enabled", False)),
        items=[EmotionItem(value=i["value"], ref=i.get("ref")) for i in items_data],
        base_emotion=BaseEmotion(
            enabled=bool(base_data.get("enabled", False)),
            value=base_data.get("value", ""),
            ref=base_data.get("ref"),
        ),
    )


def _base_outfit(data: dict[str, Any] | None) -> BaseOutfit:
    if not data:
        return BaseOutfit()
    return BaseOutfit(
        prompt=data.get("prompt", ""),
        frozen=bool(data.get("frozen", False)),
        ref=data.get("ref"),
    )


def _outfit_entry(data: dict[str, Any]) -> OutfitEntry:
    refs_data = data.get("refs") or {}
    return OutfitEntry(
        id=data["id"],
        prompt=data.get("prompt", ""),
        complex=bool(data.get("complex", False)),
        refs=OutfitRefs(
            front_full=refs_data.get("front_full"),
            back_full=refs_data.get("back_full"),
            profile_full=refs_data.get("profile_full"),
        ),
        details=[
            OutfitDetail(prompt=d.get("prompt", ""), ref=d.get("ref"))
            for d in (data.get("details") or [])
        ],
    )


def _prop_entry(data: dict[str, Any]) -> PropEntry:
    return PropEntry(
        id=data["id"],
        name=data.get("name", ""),
        shots=[
            PropShot(what=s.get("what", ""), prompt=s.get("prompt", ""), ref=s.get("ref"))
            for s in (data.get("shots") or [])
        ],
    )


def _cost_ledger(data: dict[str, Any] | None) -> CostLedger:
    if not data:
        return CostLedger()
    return CostLedger(
        image_usd=float(data.get("image_usd", 0.0) or 0.0),
        llm_usd=float(data.get("llm_usd", 0.0) or 0.0),
        image_calls=int(data.get("image_calls", 0) or 0),
        llm_calls=int(data.get("llm_calls", 0) or 0),
        has_estimate=bool(data.get("has_estimate", False)),
    )


def _step_record(data: dict[str, Any]) -> StepRecord:
    return StepRecord(
        last_path=data.get("last_path"),
        approved_path=data.get("approved_path"),
        prompt_layers=_prompt_layers(data.get("prompt_layers")),
        need_regen=bool(data.get("need_regen", False)),
        stale=bool(data.get("stale", False)),
    )


def state_from_dict(data: dict[str, Any]) -> CharacterState:
    """Inverse of :func:`state_to_dict`. Unknown keys are ignored."""
    return CharacterState(
        character_id=data["character_id"],
        name=data.get("name", ""),
        character_table=dict(data.get("character_table") or {}),
        emotions=_emotions(data.get("emotions")),
        base_outfit=_base_outfit(data.get("base_outfit")),
        outfits=[_outfit_entry(o) for o in (data.get("outfits") or [])],
        outfits_enabled=bool(data.get("outfits_enabled", False)),
        active_outfit_id=data.get("active_outfit_id", "base"),
        props_enabled=bool(data.get("props_enabled", False)),
        props=[_prop_entry(p) for p in (data.get("props") or [])],
        prompt_layers=_prompt_layers(data.get("prompt_layers")),
        style_ref=data.get("style_ref"),
        steps={k: _step_record(v) for k, v in (data.get("steps") or {}).items()},
        current_step=data.get("current_step"),
        dataset_compositions=list(data.get("dataset_compositions") or []),
        # ``str()`` coercion is deliberate defensive parsing of an external,
        # possibly hand-edited file — keys/values are forced to the declared
        # ``dict[str, str]`` shape rather than trusting the JSON types.
        scene_overrides={str(k): str(v) for k, v in (data.get("scene_overrides") or {}).items()},
        cost=_cost_ledger(data.get("cost")),
    )
