"""Tests for orchestrator wiring: agent selection and cost accounting."""

from __future__ import annotations

import pytest

from sub_checker.config import ClaimConfig, Config
from sub_checker.models import CheckerResult, Finding, Severity, TokenUsage
from sub_checker.orchestrator import _pricing_for, _usage_cost, build_report, create_agents

# --- claim.enabled toggle ---


def test_create_agents_includes_citation_claim_by_default():
    names = {a.name for a in create_agents(Config())}
    assert "citation_claim" in names


def test_create_agents_honors_claim_disabled():
    on = {a.name for a in create_agents(Config())}
    off = {a.name for a in create_agents(Config(claim=ClaimConfig(enabled=False)))}
    assert "citation_claim" not in off
    assert off == on - {"citation_claim"}


def test_create_agents_includes_figure_vision_by_default():
    names = [a.name for a in create_agents(Config())]
    assert "figure_vision" in names


def test_create_agents_omits_figure_vision_when_disabled():
    cfg = Config()
    cfg.figures.vision_enabled = False
    names = [a.name for a in create_agents(cfg)]
    assert "figure_vision" not in names


# --- cost model ---


def test_pricing_for_matches_family_and_defaults():
    assert _pricing_for("claude-opus-4-8") == (5.0, 25.0)
    assert _pricing_for("claude-sonnet-4-6") == (3.0, 15.0)
    assert _pricing_for("claude-haiku-4-5") == (1.0, 5.0)
    # Unknown model name → conservative default (not a silent $0)
    assert _pricing_for("some-future-model") == (5.0, 25.0)


def test_usage_cost_applies_cache_multipliers():
    usage = TokenUsage(
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
    )
    # opus: input 5 + cache-write 5*1.25 + cache-read 5*0.1 + output 25 = 36.75
    assert _usage_cost(usage, "claude-opus-4-8") == pytest.approx(36.75)
    # sonnet: 3 + 3.75 + 0.3 + 15 = 22.05
    assert _usage_cost(usage, "claude-sonnet-4-6") == pytest.approx(22.05)


def test_build_report_excludes_filtered_and_costs_per_result_model():
    result = CheckerResult(
        checker_name="a",
        findings=[
            Finding(checker="a", severity=Severity.ERROR, message="real error"),
            Finding(
                checker="a",
                severity=Severity.ERROR,
                message="false positive",
                validation_status="filtered",
            ),
        ],
        token_usage=TokenUsage(input_tokens=1_000_000),
        model="claude-sonnet-4-6",
    )
    report = build_report([result], manuscript_path="m.docx", journal=None, model="claude-opus-4-8")
    # Filtered finding excluded from the summary
    assert report.summary[Severity.ERROR] == 1
    # Cost uses the RESULT's model (sonnet $3/M input), not the global opus
    assert report.total_cost == pytest.approx(3.0)
