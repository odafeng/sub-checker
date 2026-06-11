"""CLI-specific pipeline: wraps the shared orchestrator with Rich progress output."""

from __future__ import annotations

from typing import Any

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from sub_checker.agents.base import BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript, Report
from sub_checker.orchestrator import build_report, filter_agents, run_all_phases


async def run_pipeline(
    manuscript: Manuscript,
    config: Config,
    agents: list[BaseCheckerAgent],
    verbose: bool = False,
    skip: set[str] | None = None,
    only: set[str] | None = None,
    manuscript_path: str = "",
) -> Report:
    """Run all checker agents with Rich progress display."""
    console = Console()
    active = filter_agents(agents, only=only, skip=skip)

    if not active:
        console.print("[yellow]No checkers to run.[/yellow]")
        from datetime import UTC, datetime

        return Report(
            manuscript_path=manuscript_path,
            timestamp=datetime.now(UTC),
            target_journal=config.journal,
        )

    # Progress display state
    progress = Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    )
    current_task = None

    async def on_progress(event: str, agent_name: str, data: dict[str, Any]) -> None:
        nonlocal current_task
        if event == "phase_start":
            if current_task is not None:
                progress.update(current_task, completed=True)
                progress.stop_task(current_task)
            names = ", ".join(data.get("agents", []))
            current_task = progress.add_task(f"Phase {data.get('phase')}: {names}", total=None)
        elif event == "agent_done" and verbose:
            console.print(
                f"  [dim]{agent_name}: {data.get('findings_count', 0)} finding(s) "
                f"in {data.get('elapsed', 0)}s[/dim]"
            )
        elif event == "agent_error":
            console.print(f"  [bold red]{agent_name} failed: {data.get('error')}[/bold red]")

    with progress:
        results, harness_usage = await run_all_phases(active, manuscript, config, on_progress)

    return build_report(
        results,
        manuscript_path=manuscript_path,
        journal=config.journal,
        model=config.model,
        harness_usage=harness_usage,
        harness_model=config.reviewer_model or config.model,
    )
