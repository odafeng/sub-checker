"""Shared orchestration logic for CLI and API.

Single source of truth for: agent creation, phase grouping, cost calculation, report building.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any

from sub_checker.agents.base import BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import CheckerResult, Finding, Manuscript, Report, Severity

logger = logging.getLogger("sub_checker.orchestrator")

# Phase definitions: which agents run in parallel within each phase
PHASE_GROUPS: list[set[str]] = [
    {"typo_grammar", "figure_table", "citation_exist"},
    {"citation_format", "journal_guidelines", "logic"},
    {"citation_claim"},
]

# Callback type for progress notifications
AgentCallback = Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, None]]
# callback(event_type, agent_name, data)


def create_agents(config: Config) -> list[BaseCheckerAgent]:
    """Create all checker agents."""
    from sub_checker.agents.citation_claim import CitationClaimAgent
    from sub_checker.agents.citation_exist import CitationExistAgent
    from sub_checker.agents.citation_format import CitationFormatAgent
    from sub_checker.agents.figure_table import FigureTableAgent
    from sub_checker.agents.journal_guidelines import JournalGuidelinesAgent
    from sub_checker.agents.logic import LogicAgent
    from sub_checker.agents.typo_grammar import TypoGrammarAgent

    model = config.model
    return [
        TypoGrammarAgent(model=model),
        FigureTableAgent(model=model),
        CitationExistAgent(model=model),
        CitationFormatAgent(model=model),
        JournalGuidelinesAgent(model=model),
        LogicAgent(model=model),
        CitationClaimAgent(model=model),
    ]


def filter_agents(
    agents: list[BaseCheckerAgent],
    only: set[str] | None = None,
    skip: set[str] | None = None,
) -> list[BaseCheckerAgent]:
    """Filter agents by --only / --skip."""
    skip = skip or set()
    result = []
    for a in agents:
        if only and a.name not in only:
            continue
        if a.name in skip:
            continue
        result.append(a)
    return result


async def run_agent_safe(
    agent: BaseCheckerAgent,
    manuscript: Manuscript,
    config: Config,
    on_progress: AgentCallback | None = None,
) -> CheckerResult:
    """Run a single agent with error handling. Never raises."""
    if on_progress:
        await on_progress("agent_start", agent.name, {})
    try:
        result = await agent.run(manuscript, config)
        if on_progress:
            await on_progress(
                "agent_done",
                agent.name,
                {
                    "findings_count": len(result.findings),
                    "elapsed": round(result.elapsed_seconds, 1),
                },
            )
        return result
    except Exception as e:
        logger.error("[%s] Agent crashed: %s", agent.name, e, exc_info=True)
        if on_progress:
            await on_progress("agent_error", agent.name, {"error": str(e)})
        return CheckerResult(
            checker_name=agent.name,
            findings=[
                Finding(checker=agent.name, severity=Severity.ERROR, message=f"Agent crashed: {e}")
            ],
        )


def build_report(
    results: list[CheckerResult],
    manuscript_path: str,
    journal: str | None,
    model: str = "",
) -> Report:
    """Build a Report from checker results. Single source of truth for cost calculation."""
    summary: dict[Severity, int] = {s: 0 for s in Severity}
    total_cost = 0.0
    for r in results:
        for f in r.findings:
            if f.validation_status != "filtered":
                summary[f.severity] = summary.get(f.severity, 0) + 1
        # Opus 4.8 pricing: $5/M input, $25/M output
        total_cost += (
            r.token_usage.input_tokens * 5 + r.token_usage.output_tokens * 25
        ) / 1_000_000

    return Report(
        manuscript_path=manuscript_path,
        timestamp=datetime.now(UTC),
        target_journal=journal,
        results=results,
        summary=summary,
        total_cost=total_cost,
        model=model,
    )


async def run_all_phases(
    agents: list[BaseCheckerAgent],
    manuscript: Manuscript,
    config: Config,
    on_progress: AgentCallback | None = None,
) -> list[CheckerResult]:
    """Execute agents in phased order, then run Phase 3 post-validation.

    Phase 1-2-3: Agent execution (parallel within each phase)
    Phase 4: Deterministic post-validation (filter obvious false positives)
    Phase 5: Reviewer agent (LLM-based validation of remaining findings)
    """
    from sub_checker.harness.deterministic import run_deterministic_checks
    from sub_checker.harness.reviewer import run_reviewer

    results: list[CheckerResult] = []

    # --- Agent execution phases ---
    for phase_num, phase_names in enumerate(PHASE_GROUPS, 1):
        phase_agents = [a for a in agents if a.name in phase_names]
        if not phase_agents:
            continue

        if on_progress:
            await on_progress(
                "phase_start", "", {"phase": phase_num, "agents": [a.name for a in phase_agents]}
            )

        phase_results = await asyncio.gather(
            *[run_agent_safe(a, manuscript, config, on_progress) for a in phase_agents]
        )
        results.extend(phase_results)

    # --- Phase 4: Deterministic post-validation ---
    if on_progress:
        await on_progress("phase_start", "", {"phase": 4, "agents": ["deterministic_check"]})
        await on_progress("agent_start", "deterministic_check", {})

    total_before = sum(len(r.findings) for r in results)
    results = run_deterministic_checks(results, manuscript)
    filtered_det = sum(1 for r in results for f in r.findings if f.validation_status == "filtered")
    logger.info(
        "Deterministic post-validation: %d/%d findings filtered", filtered_det, total_before
    )

    if on_progress:
        await on_progress(
            "agent_done", "deterministic_check", {"filtered": filtered_det, "elapsed": 0.0}
        )

    # --- Phase 5: Reviewer agent ---
    remaining = total_before - filtered_det
    if remaining > 0:
        if on_progress:
            await on_progress("phase_start", "", {"phase": 5, "agents": ["reviewer"]})
            await on_progress("agent_start", "reviewer", {})

        results = await run_reviewer(manuscript, results, model=config.model)

        if on_progress:
            confirmed = sum(
                1 for r in results for f in r.findings if f.validation_status == "confirmed"
            )
            filtered_rev = (
                sum(1 for r in results for f in r.findings if f.validation_status == "filtered")
                - filtered_det
            )
            await on_progress(
                "agent_done",
                "reviewer",
                {"confirmed": confirmed, "filtered": filtered_rev, "elapsed": 0.0},
            )

    return results
