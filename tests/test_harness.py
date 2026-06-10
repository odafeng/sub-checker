"""Tests for the post-validation harness (deterministic checks + reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime

from sub_checker.config import Config
from sub_checker.harness.deterministic import (
    run_deterministic_checks,
    validate_citation_numbers,
    validate_date_claims,
)
from sub_checker.harness.reviewer import run_reviewer
from sub_checker.models import CheckerResult, Finding, Manuscript, Severity

from .mock_helpers import MockResponse, MockToolUse, mock_anthropic_client

TODAY = datetime(2026, 6, 10, tzinfo=UTC)


def _finding(**kwargs) -> Finding:
    defaults = {"checker": "test", "severity": Severity.WARNING, "message": "msg"}
    defaults.update(kwargs)
    return Finding(**defaults)


def _manuscript(raw_text: str = "", reference_section: str | None = None) -> Manuscript:
    return Manuscript(
        title="T",
        sections=[],
        paragraphs=[],
        raw_text=raw_text,
        reference_section=reference_section,
    )


# --- validate_date_claims: structured path ---


def test_date_claim_structured_past_date_filtered():
    f = _finding(
        message="The submission date is in the future",
        claim_type="future_date",
        claimed_date="2025-11",
    )
    actions = validate_date_claims([f], today=TODAY)
    assert actions == [(0, "filter", "2025-11 is not in the future (today=2026-06-10)")]


def test_date_claim_structured_future_date_kept():
    f = _finding(
        message="The submission date is in the future",
        claim_type="future_date",
        claimed_date="2027-01",
    )
    assert validate_date_claims([f], today=TODAY) == []


def test_date_claim_prose_fallback_still_works():
    f = _finding(message="November 2025 is a future date")
    actions = validate_date_claims([f], today=TODAY)
    assert len(actions) == 1
    assert actions[0][1] == "filter"


# --- validate_citation_numbers ---


def test_uncited_reference_filtered_when_actually_cited():
    ms = _manuscript(raw_text="As shown previously [23], results hold.")
    f = _finding(
        message="Reference 23 is never used",
        claim_type="uncited_reference",
        ref_number=23,
    )
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "filter"


def test_missing_reference_only_downgraded_not_filtered():
    """Line-count ref existence is a heuristic — must not hard-delete findings."""
    ms = _manuscript(raw_text="Claim [2].", reference_section="Ref one.\nRef two.\nRef three.")
    f = _finding(
        message="Citation [2] is missing from the reference list",
        claim_type="missing_reference",
        ref_number=2,
    )
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_structured_fields_used_even_with_unparseable_prose():
    """The message doesn't match any regex pattern, but ref_number is set."""
    ms = _manuscript(raw_text="See [7] for details.")
    f = _finding(
        message="第七筆文獻似乎沒有在內文出現過",  # no regex pattern matches this
        claim_type="uncited_reference",
        ref_number=7,
    )
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "filter"


# --- severity restore through the pipeline ---


def test_deterministic_downgrade_preserves_original_severity():
    ms = _manuscript(raw_text="Claim [2].", reference_section="Ref one.\nRef two.")
    f = _finding(
        severity=Severity.ERROR,
        message="Citation [2] is missing from the reference list",
        claim_type="missing_reference",
        ref_number=2,
    )
    results = run_deterministic_checks([CheckerResult(checker_name="t", findings=[f])], ms)
    out = results[0].findings[0]
    assert out.validation_status == "downgraded"
    assert out.severity == Severity.INFO
    assert out.original_severity == Severity.ERROR


async def test_reviewer_confirm_restores_downgraded_severity():
    f = _finding(severity=Severity.INFO, message="Real issue")
    f.validation_status = "downgraded"
    f.original_severity = Severity.ERROR
    results = [CheckerResult(checker_name="t", findings=[f])]

    verdict_response = MockResponse(
        content=[
            MockToolUse(
                name="submit_verdicts",
                input={
                    "verdicts": [
                        {"index": 0, "action": "confirm", "confidence": 0.9, "reason": "verified"}
                    ]
                },
            )
        ],
        stop_reason="tool_use",
    )
    with mock_anthropic_client(
        verdict_response, target="sub_checker.harness.reviewer.anthropic.AsyncAnthropic"
    ):
        results, usage = await run_reviewer(_manuscript(raw_text="text"), results)

    out = results[0].findings[0]
    assert out.validation_status == "confirmed"
    assert out.severity == Severity.ERROR
    assert out.original_severity is None
    assert usage.input_tokens > 0


# --- agentic reviewer ---


async def test_reviewer_uses_tools_then_submits_verdicts():
    ms = Manuscript(
        title="T",
        sections=[],
        paragraphs=[],
        raw_text="Methods text mentions Pearson correlation.",
        reference_section=None,
    )
    f = _finding(message="Pearson vs Spearman mismatch")
    results = [CheckerResult(checker_name="logic", findings=[f])]

    tool_response = MockResponse(
        content=[MockToolUse(name="search_text", input={"query": "Pearson"})],
        stop_reason="tool_use",
    )
    verdict_response = MockResponse(
        content=[
            MockToolUse(
                name="submit_verdicts",
                input={
                    "verdicts": [
                        {"index": 0, "action": "filter", "confidence": 0.1, "reason": "wrong"}
                    ]
                },
            )
        ],
        stop_reason="tool_use",
    )
    with mock_anthropic_client(
        tool_response,
        verdict_response,
        target="sub_checker.harness.reviewer.anthropic.AsyncAnthropic",
    ):
        results, _ = await run_reviewer(ms, results)

    out = results[0].findings[0]
    assert out.validation_status == "filtered"
    assert out.confidence <= 0.1


async def test_reviewer_api_failure_leaves_findings_untouched():
    f = _finding(message="Some issue")
    results = [CheckerResult(checker_name="t", findings=[f])]

    from unittest.mock import AsyncMock, MagicMock, patch

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
    with patch("sub_checker.harness.reviewer.anthropic.AsyncAnthropic", return_value=mock_client):
        results, usage = await run_reviewer(_manuscript(), results)

    assert results[0].findings[0].validation_status == ""
    assert usage.input_tokens == 0


# --- per-checker model config ---


def test_model_for_uses_per_checker_override():
    config = Config()
    assert config.model_for("typo_grammar") == "claude-sonnet-4-6"
    assert config.model_for("logic") == "claude-opus-4-8"


def test_model_for_empty_overrides_falls_back_to_global():
    config = Config(models={})
    assert config.model_for("typo_grammar") == "claude-opus-4-8"
