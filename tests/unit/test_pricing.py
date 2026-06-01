"""Tests for API cost pricing, usage extraction, and the cost ledger."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from create_char_passport.gen.pricing import (
    MODEL_PRICES,
    PRICES_CAPTURED,
    CallUsage,
    extract_usage,
    image_cost,
    is_estimate,
    llm_cost,
    price_for,
    record_image,
    record_llm,
)
from create_char_passport.state import CostLedger, blank_state, state_from_dict, state_to_dict


@dataclass
class FakeMeta:
    prompt_token_count: int | None = None
    candidates_token_count: int | None = None
    thoughts_token_count: int | None = None


@dataclass
class FakeResp:
    usage_metadata: object | None = None


def test_extract_usage_reads_tokens() -> None:
    resp = FakeResp(
        FakeMeta(prompt_token_count=100, candidates_token_count=40, thoughts_token_count=10)
    )
    usage = extract_usage(resp)
    assert usage.prompt_tokens == 100
    assert usage.output_tokens == 50  # candidates + thinking tokens


def test_extract_usage_missing_metadata_is_zero() -> None:
    assert extract_usage(FakeResp(None)) == CallUsage()
    assert extract_usage(object()) == CallUsage()  # no usage_metadata attribute at all


def test_extract_usage_handles_none_fields() -> None:
    assert extract_usage(FakeResp(FakeMeta())) == CallUsage()


def test_llm_cost_known_model() -> None:
    # gemini-2.5-flash: $0.30/MTok in, $2.50/MTok out.
    usage = CallUsage(prompt_tokens=1_000_000, output_tokens=1_000_000)
    assert llm_cost("gemini-2.5-flash", usage) == pytest.approx(0.30 + 2.50)


def test_llm_cost_unknown_model_is_zero() -> None:
    assert llm_cost("mystery-model", CallUsage(prompt_tokens=1_000_000)) == 0.0


def test_image_cost() -> None:
    assert image_cost("gemini-3.1-flash-image-preview") == pytest.approx(0.04)
    assert image_cost("gemini-3-pro-image-preview", images=2) == pytest.approx(0.26)
    assert image_cost("unknown-model") == 0.0


def test_is_estimate() -> None:
    assert is_estimate("gemini-3.1-flash-image-preview") is True  # preview, approximate
    assert is_estimate("gemini-2.5-flash") is False
    assert is_estimate("totally-unknown") is True  # unknown -> treated as approximate


def test_record_llm_and_image_mutate_ledger() -> None:
    ledger = CostLedger()
    record_llm(ledger, "gemini-2.5-flash", CallUsage(prompt_tokens=1_000_000, output_tokens=0))
    assert ledger.llm_calls == 1
    assert ledger.llm_usd == pytest.approx(0.30)
    assert ledger.has_estimate is False  # exact list price
    record_image(ledger, "gemini-3-pro-image-preview")
    assert ledger.image_calls == 1
    assert ledger.image_usd == pytest.approx(0.13)
    assert ledger.total_usd == pytest.approx(0.43)
    assert ledger.has_estimate is True  # preview model -> estimate


def test_record_counts_call_even_when_unpriced() -> None:
    ledger = CostLedger()
    record_llm(ledger, "unknown-model", CallUsage(prompt_tokens=999))
    assert ledger.llm_calls == 1
    assert ledger.llm_usd == 0.0
    assert ledger.has_estimate is True  # unknown model is treated as an estimate


def test_price_table_has_documented_date_and_default_model() -> None:
    assert PRICES_CAPTURED
    assert price_for("gemini-2.5-flash").input_per_mtok == pytest.approx(0.30)
    assert "gemini-3.1-flash-image-preview" in MODEL_PRICES


def test_cost_ledger_merge_and_total() -> None:
    a = CostLedger(image_usd=0.10, llm_usd=0.20, image_calls=1, llm_calls=2)
    a.merge(CostLedger(image_usd=0.05, llm_usd=0.0, image_calls=1, llm_calls=0, has_estimate=True))
    assert a.image_usd == pytest.approx(0.15)
    assert a.llm_usd == pytest.approx(0.20)
    assert (a.image_calls, a.llm_calls) == (2, 2)
    assert a.total_usd == pytest.approx(0.35)
    assert a.has_estimate is True  # OR-ed in from the merged ledger


def test_cost_ledger_survives_state_round_trip() -> None:
    state = blank_state("Conan")
    state.cost.merge(
        CostLedger(image_usd=0.04, llm_usd=0.01, image_calls=1, llm_calls=1, has_estimate=True)
    )
    restored = state_from_dict(state_to_dict(state))
    assert restored.cost.total_usd == pytest.approx(0.05)
    assert (restored.cost.image_calls, restored.cost.llm_calls) == (1, 1)
    assert restored.cost.has_estimate is True
