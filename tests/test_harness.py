"""Tests for the post-validation harness (deterministic checks + reviewer)."""

from __future__ import annotations

from datetime import UTC, datetime

from sub_checker.config import Config
from sub_checker.harness.deterministic import (
    run_deterministic_checks,
    validate_citation_numbers,
    validate_date_claims,
    validate_self_consistency,
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
    assert actions == [(0, "filter", "2025-11 is entirely in the past (today=2026-06-10)")]


def test_date_claim_structured_future_date_kept():
    f = _finding(
        message="The submission date is in the future",
        claim_type="future_date",
        claimed_date="2027-01",
    )
    assert validate_date_claims([f], today=TODAY) == []


def test_date_claim_current_year_downgraded_not_filtered():
    # "2026" with today=2026-06-10: December 2026 is still in the future, so a
    # year-granular claim must NOT be hard-filtered — only downgraded.
    f = _finding(
        message="The date is in the future",
        claim_type="future_date",
        claimed_date="2026",
    )
    actions = validate_date_claims([f], today=TODAY)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_date_claim_current_month_downgraded_not_filtered():
    f = _finding(
        message="The date is in the future",
        claim_type="future_date",
        claimed_date="2026-06",
    )
    actions = validate_date_claims([f], today=TODAY)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_date_claim_future_month_of_current_year_kept():
    f = _finding(
        message="The date is in the future",
        claim_type="future_date",
        claimed_date="2026-12",
    )
    assert validate_date_claims([f], today=TODAY) == []


def test_date_claim_chinese_prose_current_year_not_filtered():
    # "2026年12月 是未來日期" — the English-month regex can't match, the
    # year-only fallback sees 2026; it must not hard-filter a true finding.
    f = _finding(message="2026年12月 是未來日期")
    actions = validate_date_claims([f], today=TODAY)
    assert all(a[1] != "filter" for a in actions)


def test_date_claim_prose_fallback_downgrades_not_filters():
    # A prose future-date claim WITHOUT structured fields is a heuristic match
    # (proximity of a date to "future"), so it may only be downgraded — the
    # reviewer confirms it. Hard-filtering here can silently delete real
    # findings (see test below), which the module's fail-safe rule forbids.
    f = _finding(message="November 2025 is a future date")
    actions = validate_date_claims([f], today=TODAY)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_date_claim_prose_past_date_near_future_word_not_filtered():
    # Regression: a finding that merely MENTIONS a past date near "future" is
    # not a future-date claim and must never be hard-deleted.
    for msg in (
        "Results from 2018 will inform future guidelines.",
        "The Methods describe March 2020 enrollment, but future work is discussed.",
        "2019年的資料將用於未來的分析。",
    ):
        f = _finding(message=msg)
        actions = validate_date_claims([f], today=TODAY)
        assert all(a[1] != "filter" for a in actions), f"wrongly filtered: {msg!r}"


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


def test_uncited_reference_paren_only_downgraded_not_filtered():
    # "(1) ... (2) ..." are inline enumerations, not citations. A genuinely
    # uncited reference [1] must NOT be hard-filtered just because "(1)" appears
    # as an enumeration marker — that would silently delete a real finding.
    ms = _manuscript(raw_text="Aims: (1) assess safety, (2) evaluate efficacy, (3) measure cost.")
    f = _finding(
        message="Reference 1 is never cited",
        claim_type="uncited_reference",
        ref_number=1,
    )
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_uncited_superscript_citation_downgraded_not_filtered():
    # A superscript citation [15] contradicts an "uncited [15]" claim, but
    # superscript is NOT in the filter-capable set → downgrade, never filter.
    ms = _manuscript(raw_text="No bracketed citations here.")
    ms.superscript_citations = {15}
    f = _finding(
        message="Reference 15 is never cited", claim_type="uncited_reference", ref_number=15
    )
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_superscript_exponent_cannot_hard_filter():
    # Even if an exponent like m² is mis-read as superscript "2", an
    # "uncited [2]" finding is only downgraded, never deleted.
    ms = _manuscript(raw_text="Area was 4 m2 in size.")
    ms.superscript_citations = {2}  # as the parser would yield for m²
    f = _finding(message="Reference 2 is never cited", claim_type="uncited_reference", ref_number=2)
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_uncited_reference_square_bracket_is_exact_and_filtered():
    # A square-bracket citation is unambiguous, so the "never cited" claim is
    # provably wrong and may be filtered.
    ms = _manuscript(raw_text="As shown [3], the effect holds.")
    f = _finding(message="Reference 3 is never cited", claim_type="uncited_reference", ref_number=3)
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "filter"


# --- validate_self_consistency ---


def test_self_consistency_downgrades_when_examples_share_pattern():
    f = _finding(
        message="Inconsistent naming: field_name is snake_case",
        suggestion="But other_field also uses underscores",
        claim_type="inconsistency",
    )
    actions = validate_self_consistency([f])
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_self_consistency_ignores_single_repeated_token():
    # The same identifier repeated across message+suggestion is ONE example,
    # not a genuine inconsistency, so no action is taken.
    f = _finding(
        message="Inconsistent: field_name should be camelCase",
        suggestion="Rename field_name to fieldName",
        claim_type="inconsistency",
    )
    assert validate_self_consistency([f]) == []


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


async def test_reviewer_multi_batch_rejects_cross_batch_index(monkeypatch):
    # >25 findings span two batches. Each batch's verdicts must be applied by
    # GLOBAL index, and a verdict whose index falls outside the emitting batch
    # (a model returning batch-local indices) must be rejected, not silently
    # overwrite another batch's finding (reviewer.py bounds guard).
    import sub_checker.harness.reviewer as rev

    findings = [_finding(message=f"issue {n}") for n in range(30)]
    results = [CheckerResult(checker_name="t", findings=findings)]

    async def fake_review_batch(_client, _model, _manuscript, _context, batch, _usage):
        verdicts = [
            {"index": gidx, "action": "confirm", "confidence": 0.9, "reason": "ok"}
            for gidx, _ in batch
        ]
        # The second batch (global indices 25..29) also emits a verdict for
        # index 0 — which belongs to batch 1 — to prove it gets rejected.
        if batch[0][0] == 25:
            verdicts.append(
                {"index": 0, "action": "filter", "confidence": 0.0, "reason": "cross-batch leak"}
            )
        return verdicts

    monkeypatch.setattr(rev, "_review_batch", fake_review_batch)
    out, _ = await run_reviewer(_manuscript(raw_text="text"), results)

    fs = out[0].findings
    # All 30 confirmed via their own global index (batch 2 included)...
    assert all(f.validation_status == "confirmed" for f in fs)
    # ...and finding[0] was NOT flipped to "filtered" by batch 2's stray index.
    assert fs[0].validation_status == "confirmed"


async def test_reviewer_api_failure_leaves_findings_untouched():
    f = _finding(message="Some issue")
    results = [CheckerResult(checker_name="t", findings=[f])]

    from unittest.mock import AsyncMock, MagicMock, patch

    mock_client = MagicMock()
    mock_client.messages.create = AsyncMock(side_effect=RuntimeError("API down"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
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


# --- deterministic conflict resolution: strongest action wins ---


def test_filter_not_overwritten_by_later_downgrade(monkeypatch):
    # Two validators flag the SAME finding index with different actions. The
    # stronger "filter" (hide) must win regardless of validator order, so a
    # provably-wrong finding is never resurrected as a downgraded INFO.
    import sub_checker.harness.deterministic as det

    for order in (("filter", "downgrade"), ("downgrade", "filter")):
        first, second = order
        monkeypatch.setattr(det, "validate_date_claims", lambda _f, a=first: [(0, a, a)])
        monkeypatch.setattr(det, "validate_citation_numbers", lambda _f, _m, b=second: [(0, b, b)])
        monkeypatch.setattr(det, "validate_self_consistency", lambda _f: [])

        f = _finding(severity=Severity.ERROR, message="conflicting finding")
        results = det.run_deterministic_checks(
            [CheckerResult(checker_name="t", findings=[f])], _manuscript()
        )
        out = results[0].findings[0]
        assert out.validation_status == "filtered", f"order={order}"
        assert out.confidence == 0.0


# --- config: secrets come from the environment, never the committed file ---


def test_pubmed_credentials_read_from_env(monkeypatch):
    from sub_checker.config import load_config

    monkeypatch.setenv("PUBMED_API_KEY", "env-key-123")
    monkeypatch.setenv("PUBMED_EMAIL", "env@example.com")
    config = load_config()  # no file → defaults (null credentials) + env fallback
    assert config.claim.pubmed_api_key == "env-key-123"
    assert config.claim.pubmed_email == "env@example.com"


def test_pubmed_credentials_none_without_env(monkeypatch):
    from sub_checker.config import load_config

    monkeypatch.delenv("PUBMED_API_KEY", raising=False)
    monkeypatch.delenv("PUBMED_EMAIL", raising=False)
    config = load_config()
    assert config.claim.pubmed_api_key is None
    assert config.claim.pubmed_email is None


def test_web_cache_can_be_disabled_or_resolved(tmp_path):
    from sub_checker.config import Config

    disabled = Config(web_cache_dir=None)
    enabled = Config(web_cache_dir=str(tmp_path))

    assert disabled.web_cache_path() is None
    assert enabled.web_cache_path() == tmp_path / "web.json"


# --- reviewer completeness: partial verdicts don't silently drop findings ---


async def test_reviewer_flags_findings_with_no_verdict(monkeypatch):
    # The model returns a verdict for only one of three batched findings. The
    # two uncovered findings must stay visible (status unchanged) and carry a
    # traceable note rather than being silently left unreviewed.
    import sub_checker.harness.reviewer as rev

    findings = [_finding(message=f"issue {n}") for n in range(3)]
    results = [CheckerResult(checker_name="t", findings=findings)]

    async def fake_review_batch(_client, _model, _manuscript, _context, batch, _usage):
        first_gidx = batch[0][0]
        return [{"index": first_gidx, "action": "confirm", "confidence": 0.9, "reason": "ok"}]

    monkeypatch.setattr(rev, "_review_batch", fake_review_batch)
    out, _ = await run_reviewer(_manuscript(raw_text="text"), results)

    fs = out[0].findings
    assert fs[0].validation_status == "confirmed"
    # Uncovered findings remain visible (not filtered) and are flagged.
    for f in fs[1:]:
        assert f.validation_status == ""
        assert "no verdict" in f.validation_note
