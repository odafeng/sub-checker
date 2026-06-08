"""Markdown reporter."""

from __future__ import annotations

from sub_checker.models import Report, Severity


def format_markdown(report: Report) -> str:
    lines = [
        "# Sub-Checker Report",
        "",
        f"- **Journal**: {report.target_journal or 'Not specified'}",
        f"- **Time**: {report.timestamp:%Y-%m-%d %H:%M:%S UTC}",
        f"- **Estimated cost**: ${report.total_cost:.2f}",
        "",
        "## Summary",
        "",
        f"- Errors: {report.summary.get(Severity.ERROR, 0)}",
        f"- Warnings: {report.summary.get(Severity.WARNING, 0)}",
        f"- Info: {report.summary.get(Severity.INFO, 0)}",
        "",
    ]

    for result in report.results:
        lines.append(f"## {result.checker_name} ({result.elapsed_seconds:.1f}s)")
        lines.append("")

        if not result.findings:
            lines.append("No issues found.")
            lines.append("")
            continue

        lines.append("| Severity | Location | Message | Suggestion |")
        lines.append("|----------|----------|---------|------------|")

        for f in result.findings:
            loc = f.location or "-"
            sug = f.suggestion or "-"
            lines.append(f"| {f.severity.value} | {loc} | {f.message} | {sug} |")

        lines.append("")

    return "\n".join(lines)
