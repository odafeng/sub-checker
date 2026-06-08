"""Rich terminal reporter with i18n support."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sub_checker.i18n import checker_display_name, t
from sub_checker.models import Report, Severity

_SEVERITY_STYLE = {
    Severity.ERROR: "[bold red]{label}[/bold red]",
    Severity.WARNING: "[yellow]{label}[/yellow]",
    Severity.INFO: "[dim]{label}[/dim]",
}
_SEVERITY_KEY = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info_label"}


def print_report(report: Report, console: Console | None = None, lang: str = "en") -> None:
    console = console or Console()
    tr = lambda key: t(key, lang)  # noqa: E731

    # Header
    console.print()
    console.print(
        Panel(
            f"[bold]{tr('report_title')}[/bold]\n"
            f"{tr('journal_label')}: {report.target_journal or tr('journal_not_specified')}\n"
            f"{tr('generated')}: {report.timestamp:%Y-%m-%d %H:%M:%S UTC}",
            title="sub-check",
        )
    )

    # Summary
    errors = report.summary.get(Severity.ERROR, 0)
    warnings = report.summary.get(Severity.WARNING, 0)
    infos = report.summary.get(Severity.INFO, 0)
    console.print(
        f"\n[bold red]{errors} {tr('errors').lower()}[/bold red] | "
        f"[yellow]{warnings} {tr('warnings').lower()}[/yellow] | "
        f"[dim]{infos} {tr('info').lower()}[/dim] | "
        f"{tr('est_cost')}: ${report.total_cost:.2f}\n"
    )

    # Findings by checker
    for result in report.results:
        display = checker_display_name(result.checker_name, lang)
        if not result.findings:
            console.print(f"[green]  {display}: {tr('no_issues')}[/green]")
            continue

        table = Table(title=f"{display} ({result.elapsed_seconds:.1f}s)")
        table.add_column(tr("severity"), width=10)
        table.add_column(tr("location"), width=25)
        table.add_column(tr("message"), ratio=2)
        table.add_column(tr("suggestion"), ratio=1)

        for f in result.findings:
            sev_label = tr(_SEVERITY_KEY[f.severity])
            styled = _SEVERITY_STYLE[f.severity].format(label=sev_label)
            table.add_row(
                styled,
                f.location or "—",
                f.message,
                f.suggestion or "—",
            )

        console.print(table)
        console.print()
