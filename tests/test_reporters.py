"""Tests for report rendering: HTML escaping and filtered-finding exclusion."""

from __future__ import annotations

from sub_checker.models import CheckerResult, Finding, Severity
from sub_checker.orchestrator import build_report
from sub_checker.reporters.html_reporter import format_html
from sub_checker.reporters.json_reporter import format_json
from sub_checker.reporters.markdown_reporter import format_markdown


def _report(findings: list[Finding]):
    result = CheckerResult(checker_name="logic", findings=findings)
    return build_report([result], manuscript_path="m.docx", journal=None, model="claude-opus-4-8")


def test_html_confidence_badge_survives_none_confidence():
    # A confirmed/downgraded finding whose confidence is None must not crash the
    # HTML reporter (the `{f.confidence:.0%}` format would raise on None).
    f = Finding(checker="logic", severity=Severity.WARNING, message="msg")
    f.validation_status = "confirmed"
    f.confidence = None  # type: ignore[assignment]  # slips through at runtime (no validate_assignment)
    html = format_html(_report([f]))
    assert "msg" in html  # rendered without a confidence badge, no exception


def test_html_escapes_finding_text():
    # Finding text is derived from the manuscript and the model, and the HTML
    # report is served to browsers — so every field must be escaped.
    f = Finding(
        checker="logic",
        severity=Severity.ERROR,
        message="<script>alert(1)</script>",
        location='x" onerror="alert(1)',
        suggestion="<img src=x onerror=alert(2)>",
        context="<b>ctx</b>",
    )
    html = format_html(_report([f]))
    assert "<script>alert(1)</script>" not in html
    assert "<img src=x" not in html
    assert ' onerror="alert(1)' not in html
    # The escaped form is present (so the text is shown, just inert)
    assert "&lt;script&gt;" in html


def test_reporters_exclude_filtered_findings():
    active = Finding(checker="logic", severity=Severity.WARNING, message="ACTIVEMARK_keep")
    filtered = Finding(
        checker="logic",
        severity=Severity.ERROR,
        message="FILTEREDMARK_drop",
        validation_status="filtered",
    )
    report = _report([active, filtered])
    for render in (format_html(report), format_json(report), format_markdown(report)):
        assert "ACTIVEMARK_keep" in render
        assert "FILTEREDMARK_drop" not in render
