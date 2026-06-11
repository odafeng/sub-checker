"""Markdown reporter with i18n support."""

from __future__ import annotations

from sub_checker.i18n import checker_display_name, t
from sub_checker.models import Report, Severity

_SEVERITY_KEY = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info_label"}


def _cell(text: str | None, fallback: str = "—") -> str:
    """Escape untrusted text for a markdown table cell."""
    if not text:
        return fallback
    return text.replace("|", "\\|").replace("\n", "<br>")


def format_markdown(report: Report, lang: str = "en") -> str:
    tr = lambda key: t(key, lang)  # noqa: E731

    lines = [
        f"# {tr('report_title')}",
        "",
        f"- **{tr('journal_label')}**: {report.target_journal or tr('journal_not_specified')}",
        f"- **{tr('generated')}**: {report.timestamp:%Y-%m-%d %H:%M:%S UTC}",
        f"- **{tr('est_cost')}**: ${report.total_cost:.2f}",
        "",
        f"## {tr('summary')}",
        "",
        f"- {tr('errors')}: {report.summary.get(Severity.ERROR, 0)}",
        f"- {tr('warnings')}: {report.summary.get(Severity.WARNING, 0)}",
        f"- {tr('info')}: {report.summary.get(Severity.INFO, 0)}",
        "",
    ]

    for result in report.results:
        display = checker_display_name(result.checker_name, lang)
        lines.append(f"## {display} ({result.elapsed_seconds:.1f}s)")
        lines.append("")

        active_findings = result.active_findings
        if not active_findings:
            lines.append(tr("no_issues"))
            lines.append("")
            continue

        lines.append(
            f"| {tr('severity')} | {tr('location')} | {tr('message')} | {tr('suggestion')} |"
        )
        lines.append("|----------|----------|---------|------------|")

        for f in active_findings:
            sev = tr(_SEVERITY_KEY[f.severity])
            lines.append(
                f"| {sev} | {_cell(f.location)} | {_cell(f.message)} | {_cell(f.suggestion)} |"
            )

        lines.append("")

    return "\n".join(lines)
