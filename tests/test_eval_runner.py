"""Tests for the eval runner's matching and evaluation logic (no API calls)."""

from __future__ import annotations

from pathlib import Path

from sub_checker.eval_runner import GoldenCase, GoldenItem, Matcher, evaluate_case, load_golden
from sub_checker.models import Finding, Severity


def _finding(**kwargs) -> Finding:
    defaults = {"checker": "test", "severity": Severity.WARNING, "message": "msg"}
    defaults.update(kwargs)
    return Finding(**defaults)


def test_matcher_keywords_all_must_match():
    f = _finding(message="Reference [23] is not cited in the text")
    assert Matcher(keywords=["[23]", "not cited"]).matches(f)
    assert not Matcher(keywords=["[23]", "duplicate"]).matches(f)


def test_matcher_is_case_insensitive_and_spans_fields():
    f = _finding(message="Typo found", suggestion="Change to 'promising'")
    assert Matcher(keywords=["PROMISING"]).matches(f)


def test_matcher_structured_fields():
    f = _finding(message="x", claim_type="uncited_reference", ref_number=7)
    assert Matcher(claim_type="uncited_reference", ref_number=7).matches(f)
    assert not Matcher(claim_type="uncited_reference", ref_number=8).matches(f)
    assert not Matcher(checker="other").matches(f)


def test_evaluate_found_missed_and_wrongly_filtered():
    surviving = _finding(message="misspelling: promissing")
    killed = _finding(message="Figure 3 file is missing")
    killed.validation_status = "filtered"
    golden = GoldenCase(
        expected=[
            GoldenItem(id="typo", matcher=Matcher(keywords=["promissing"])),
            GoldenItem(id="fig3", matcher=Matcher(keywords=["Figure 3"])),
            GoldenItem(id="never", matcher=Matcher(keywords=["nonexistent"])),
        ]
    )
    outcome = evaluate_case([surviving, killed], golden, "case")
    assert outcome.found == ["typo"]
    assert outcome.wrongly_filtered == ["fig3"]
    assert outcome.missed == ["never"]
    assert not outcome.passed


def test_evaluate_forbidden_leak_and_catch():
    leaked_fp = _finding(message="November 2025 is a future date")
    caught_fp = _finding(message="Reference [2] is not cited")
    caught_fp.validation_status = "filtered"
    golden = GoldenCase(
        forbidden=[
            GoldenItem(id="fp-date", matcher=Matcher(keywords=["November 2025"])),
            GoldenItem(id="fp-ref2", matcher=Matcher(keywords=["[2]"])),
        ]
    )
    outcome = evaluate_case([leaked_fp, caught_fp], golden, "case")
    assert outcome.leaked == ["fp-date"]
    assert outcome.caught_fps == ["fp-ref2"]
    assert not outcome.passed


def test_evaluate_noise_counts_unmatched_surviving_findings():
    expected_hit = _finding(message="promissing typo")
    unlabelled = _finding(message="something nobody labelled")
    golden = GoldenCase(expected=[GoldenItem(id="typo", matcher=Matcher(keywords=["promissing"]))])
    outcome = evaluate_case([expected_hit, unlabelled], golden, "case")
    assert outcome.noise == 1
    assert outcome.passed  # noise alone doesn't fail a case


def test_load_golden_yaml(tmp_path: Path):
    golden_file = tmp_path / "golden.yaml"
    golden_file.write_text(
        """\
journal: "The Lancet"
checkers: [typo_grammar]
lang: zh-TW
expected:
  - id: t1
    checker: typo_grammar
    keywords: ["promissing"]
forbidden:
  - id: f1
    claim_type: uncited_reference
    ref_number: 2
"""
    )
    golden = load_golden(golden_file)
    assert golden.journal == "The Lancet"
    assert golden.checkers == ["typo_grammar"]
    assert golden.lang == "zh-TW"
    assert golden.expected[0].matcher.keywords == ["promissing"]
    assert golden.forbidden[0].matcher.ref_number == 2
