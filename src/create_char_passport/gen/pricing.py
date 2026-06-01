"""API cost estimation — the price table + usage extraction (HLE-664 / §7).

The whole app is a thin orchestrator over paid APIs; all cost lives in the
LLM and image-gen calls. This module turns a Gemini response into a USD
estimate so the UI can show a running per-character / per-session figure.

Two pricing shapes:

* **LLM** (text) — billed per token. We read the response's ``usage_metadata``
  (``prompt_token_count`` for input; ``candidates_token_count`` plus
  ``thoughts_token_count`` for output) and multiply by the model's per-MTok
  rate. This is exact given the API's own token counts.
* **image-gen** — billed per generated image. We charge a flat per-image rate
  (one image per successful ``generate_image`` call). This is the figure
  Google quotes for Nano Banana and is accurate to a small approximation.

Prices are **list prices in USD, captured on the date below** — edit
:data:`MODEL_PRICES` when Google changes them. Preview image models have no
published list price yet, so their per-image rate is a best-effort estimate
(the running total is therefore "≈", shown that way in the UI). An unknown
model contributes 0 USD but the call is still counted.

# PLAYBOOK-START
# id: usage-metadata-cost-meter
# title: Cost metering at the single API call site
# status: draft
# category: observability
# tags: [cost, llm, metering]
# When every paid API call funnels through one function, capture the
# provider's own usage metadata there and fold the priced result into a
# caller-supplied accumulator (not a global). The caller decides attribution
# (per-entity, per-session) and persistence; failed calls record nothing.
# Generalizes to any metered upstream (tokens, images, compute-seconds).
# PLAYBOOK-END
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from create_char_passport.state import CostLedger

# List prices (USD), captured 2026-06-01. EDIT HERE when Google updates pricing.
PRICES_CAPTURED = "2026-06-01"


@dataclass(frozen=True, slots=True)
class ModelPrice:
    """USD pricing for one model. LLM uses per-MTok; image-gen uses per-image."""

    input_per_mtok: float = 0.0
    output_per_mtok: float = 0.0
    per_image: float = 0.0
    # True when the figure is a best-effort estimate (e.g. unpublished preview).
    approximate: bool = False


# LLM models use per-MTok token rates. Image models are priced ALL-IN per
# generated image (``record_image`` only ever charges ``per_image``): the small
# per-call input-token cost is folded into that figure — a documented
# approximation, so image entries deliberately leave the token rates at 0.
# Sources: Gemini API pricing page (2.5-flash family). Nano Banana 2 / Pro are
# preview models with no public list price → estimated from the §7 range
# ($0.04–0.13/image) and flagged ``approximate``.
MODEL_PRICES: dict[str, ModelPrice] = {
    "gemini-2.5-flash": ModelPrice(input_per_mtok=0.30, output_per_mtok=2.50),
    "gemini-2.5-flash-image": ModelPrice(per_image=0.039),
    "gemini-3.1-flash-image-preview": ModelPrice(per_image=0.04, approximate=True),
    "gemini-3-pro-image-preview": ModelPrice(per_image=0.13, approximate=True),
}


@dataclass(slots=True)
class CallUsage:
    """Token counts pulled from one response's ``usage_metadata``."""

    prompt_tokens: int = 0
    output_tokens: int = 0


def extract_usage(response: Any) -> CallUsage:
    """Read token counts off a Gemini response, tolerating a missing field.

    Output tokens fold in ``thoughts_token_count`` (thinking tokens are billed
    at the output rate). Anything absent counts as zero.
    """
    meta = getattr(response, "usage_metadata", None)
    if meta is None:
        return CallUsage()
    prompt = int(getattr(meta, "prompt_token_count", 0) or 0)
    candidates = int(getattr(meta, "candidates_token_count", 0) or 0)
    thoughts = int(getattr(meta, "thoughts_token_count", 0) or 0)
    return CallUsage(prompt_tokens=prompt, output_tokens=candidates + thoughts)


def price_for(model: str) -> ModelPrice:
    """Price entry for ``model`` — a zero-cost entry when the model is unknown."""
    return MODEL_PRICES.get(model, ModelPrice(approximate=True))


def is_estimate(model: str) -> bool:
    """True if ``model``'s price is a best-effort estimate (preview / unknown)."""
    return price_for(model).approximate


def llm_cost(model: str, usage: CallUsage) -> float:
    """USD cost of one LLM call from its token usage."""
    price = price_for(model)
    return (
        usage.prompt_tokens * price.input_per_mtok + usage.output_tokens * price.output_per_mtok
    ) / 1_000_000


def image_cost(model: str, images: int = 1) -> float:
    """USD cost of ``images`` generated frames on ``model``."""
    return price_for(model).per_image * images


def record_llm(ledger: CostLedger, model: str, usage: CallUsage) -> None:
    """Add one LLM call's cost to ``ledger`` (count it even if the rate is 0)."""
    ledger.llm_usd += llm_cost(model, usage)
    ledger.llm_calls += 1
    ledger.has_estimate = ledger.has_estimate or is_estimate(model)


def record_image(ledger: CostLedger, model: str, images: int = 1) -> None:
    """Add one image-gen call's cost to ``ledger`` (count it even if the rate is 0)."""
    ledger.image_usd += image_cost(model, images)
    ledger.image_calls += 1
    ledger.has_estimate = ledger.has_estimate or is_estimate(model)
