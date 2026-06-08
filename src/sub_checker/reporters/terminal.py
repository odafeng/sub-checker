"""Rich terminal reporter."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from sub_checker.models import Report, Severity

_SEVERITY_STYLE = {
    Severity.ERROR: "[bold red]ERROR[/bold red]",
    Severity.WARNING: "[yellow]WARNING[/yellow]",
    Severity.INFO: "[dim]INFO[/dim]",
}


def print_report(report: Report, console: Console | None = None) -> None:
    console = console or Console()

    # Header
    console.print()
    console.print(
        Panel(
            f"[bold]Sub-Checker Report[/bold]\n"
            f"Journal: {report.target_journal or 'Not specified'}\n"
            f"Time: {report.timestamp:%Y-%m-%d %H:%M:%S UTC}",
            title="sub-check",
        )
    )

    # Summary
    errors = report.summary.get(Severity.ERROR, 0)
    warnings = report.summary.get(Severity.WARNING, 0)
    infos = report.summary.get(Severity.INFO, 0)
    console.print(
        f"\n[bold red]{errors} error(s)[/bold red] | "
        f"[yellow]{warnings} warning(s)[/yellow] | "
        f"[dim]{infos} info(s)[/dim] | "
        f"Est. cost: ${report.total_cost:.2f}\n"
    )

    # Findings by checker
    for result in report.results:
        if not result.findings:
            console.print(f"[green]  {result.checker_name}: No issues found[/green]")
            continue

        table = Table(title=f"{result.checker_name} ({result.elapsed_seconds:.1f}s)")
        table.add_column("Severity", width=10)
        table.add_column("Location", width=25)
        table.add_column("Message", ratio=2)
        table.add_column("Suggestion", ratio=1)

        for f in result.findings:
            table.add_row(
                _SEVERITY_STYLE.get(f.severity, str(f.severity.value)),
                f.location or "-",
                f.message,
                f.suggestion or "-",
            )

        console.print(table)
        console.print()
