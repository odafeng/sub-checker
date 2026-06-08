from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from sub_checker.agents.base import BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import CheckerResult, Finding, Manuscript, Report, Severity

logger = logging.getLogger("sub_checker.pipeline")


async def _run_agent(
    agent: BaseCheckerAgent,
    manuscript: Manuscript,
    config: Config,
    console: Console,
    verbose: bool = False,
) -> CheckerResult:
    """Run a single agent, catching errors so other agents can continue."""
    if verbose:
        console.print(f"  [dim]Starting {agent.name} agent...[/dim]")
    try:
        result = await agent.run(manuscript, config)
        n = len(result.findings)
        if verbose:
            console.print(
                f"  [dim]{agent.name}: {n} finding(s) in {result.elapsed_seconds:.1f}s[/dim]"
            )
        return result
    except Exception as e:
        logger.error("[%s] Agent crashed: %s", agent.name, e, exc_info=True)
        console.print(f"  [bold red]{agent.name} failed: {e}[/bold red]")
        return CheckerResult(
            checker_name=agent.name,
            findings=[
                Finding(
                    checker=agent.name,
                    severity=Severity.ERROR,
                    message=f"Agent crashed: {e}",
                )
            ],
        )


async def run_pipeline(
    manuscript: Manuscript,
    config: Config,
    agents: list[BaseCheckerAgent],
    verbose: bool = False,
    skip: set[str] | None = None,
    only: set[str] | None = None,
) -> Report:
    """Run all checker agents and produce a report."""
    console = Console()
    skip = skip or set()

    # Filter agents
    active = []
    for a in agents:
        if only and a.name not in only:
            continue
        if a.name in skip:
            continue
        active.append(a)

    if not active:
        console.print("[yellow]No checkers to run.[/yellow]")
        return Report(
            manuscript_path=str(manuscript.figure_dir or ""),
            timestamp=datetime.now(UTC),
            target_journal=config.journal,
        )

    # Phase 1: offline agents (parallel)
    phase1_names = {"typo_grammar", "figure_table", "citation_exist"}
    # Phase 2: web-dependent agents (parallel)
    phase2_names = {"citation_format", "journal_guidelines", "logic"}
    # Phase 3: sequential (depends on earlier results)
    phase3_names = {"citation_claim"}

    results: list[CheckerResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for phase_num, phase_names in enumerate([phase1_names, phase2_names, phase3_names], 1):
            phase_agents = [a for a in active if a.name in phase_names]
            if not phase_agents:
                continue

            task = progress.add_task(
                f"Phase {phase_num}: {', '.join(a.name for a in phase_agents)}",
                total=None,
            )

            phase_results = await asyncio.gather(
                *[_run_agent(a, manuscript, config, console, verbose) for a in phase_agents]
            )
            results.extend(phase_results)
            progress.update(task, completed=True)

    # Build summary
    summary: dict[Severity, int] = {s: 0 for s in Severity}
    total_cost = 0.0
    for r in results:
        for f in r.findings:
            summary[f.severity] = summary.get(f.severity, 0) + 1
        # Rough cost estimate (Sonnet pricing)
        total_cost += (
            r.token_usage.input_tokens * 3 + r.token_usage.output_tokens * 15
        ) / 1_000_000

    return Report(
        manuscript_path=str(manuscript.figure_dir or ""),
        timestamp=datetime.now(UTC),
        target_journal=config.journal,
        results=results,
        summary=summary,
        total_cost=total_cost,
    )
