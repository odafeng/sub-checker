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
from sub_checker.models import CheckerResult, Finding, Manuscript, Report, Severity, TokenUsage

logger = logging.getLogger("sub_checker.orchestrator")

# (input, output) USD per million tokens, matched by substring of the model name.
# Cache writes cost 1.25x input; cache reads cost 0.1x input.
_MODEL_PRICING: list[tuple[str, float, float]] = [
    ("opus", 5.0, 25.0),
    ("sonnet", 3.0, 15.0),
    ("haiku", 1.0, 5.0),
]
_DEFAULT_PRICING = (5.0, 25.0)


def _pricing_for(model: str) -> tuple[float, float]:
    for key, inp, out in _MODEL_PRICING:
        if key in model.lower():
            return (inp, out)
    return _DEFAULT_PRICING


def _usage_cost(usage: TokenUsage, model: str) -> float:
    inp, out = _pricing_for(model)
    return (
        usage.input_tokens * inp
        + usage.cache_creation_input_tokens * inp * 1.25
        + usage.cache_read_input_tokens * inp * 0.1
        + usage.output_tokens * out
    ) / 1_000_000


# Scheduling order: light/fast checkers first, citation_claim last (it runs
# an expensive multi-source pre-pass). No data flows between checkers, so a
# global concurrency cap replaces phase barriers — a slow checker no longer
# blocks unrelated ones.
AGENT_ORDER: list[str] = [
    "typo_grammar",
    "figure_table",
    "citation_exist",
    "citation_format",
    "journal_guidelines",
    "logic",
    "citation_claim",
]

# Callback type for progress notifications
AgentCallback = Callable[[str, str, dict[str, Any]], Coroutine[Any, Any, None]]
# callback(event_type, agent_name, data)


async def _notify(
    on_progress: AgentCallback | None, event: str, name: str, data: dict[str, Any]
) -> None:
    """Invoke the progress callback, never letting it break the pipeline.

    A WebSocket that disconnects mid-run must not crash the run or discard
    an agent's (already paid-for) results.
    """
    if on_progress is None:
        return
    try:
        await on_progress(event, name, data)
    except Exception as e:
        logger.warning("Progress callback failed for %s/%s: %s", event, name, e)


def create_agents(config: Config) -> list[BaseCheckerAgent]:
    """Create all checker agents."""
    from sub_checker.agents.citation_claim import CitationClaimAgent
    from sub_checker.agents.citation_exist import CitationExistAgent
    from sub_checker.agents.citation_format import CitationFormatAgent
    from sub_checker.agents.figure_table import FigureTableAgent
    from sub_checker.agents.journal_guidelines import JournalGuidelinesAgent
    from sub_checker.agents.logic import LogicAgent
    from sub_checker.agents.typo_grammar import TypoGrammarAgent

    classes = [
        TypoGrammarAgent,
        FigureTableAgent,
        CitationExistAgent,
        CitationFormatAgent,
        JournalGuidelinesAgent,
        LogicAgent,
        CitationClaimAgent,
    ]
    return [cls(model=config.model_for(cls.name)) for cls in classes]


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
    await _notify(on_progress, "agent_start", agent.name, {})
    try:
        result = await agent.run(manuscript, config)
    except Exception as e:
        logger.error("[%s] Agent crashed: %s", agent.name, e, exc_info=True)
        await _notify(on_progress, "agent_error", agent.name, {"error": str(e)})
        return CheckerResult(
            checker_name=agent.name,
            findings=[
                Finding(
                    checker=agent.name,
                    severity=Severity.ERROR,
                    message=f"Agent crashed: {e}",
                    # Pre-confirmed: this is an operational notice, not a
                    # manuscript claim — the reviewer must not filter it.
                    validation_status="confirmed",
                    validation_note="[harness] agent crash notice, not reviewed",
                )
            ],
        )
    await _notify(
        on_progress,
        "agent_done",
        agent.name,
        {
            "findings_count": len(result.findings),
            "elapsed": round(result.elapsed_seconds, 1),
        },
    )
    return result


def build_report(
    results: list[CheckerResult],
    manuscript_path: str,
    journal: str | None,
    model: str = "",
    harness_usage: TokenUsage | None = None,
    harness_model: str = "",
) -> Report:
    """Build a Report from checker results. Single source of truth for cost calculation.

    Each result is costed with the model that actually produced it (checkers
    may run on different models). harness_usage is the reviewer agent's token
    usage, costed with harness_model (falls back to `model`).
    """
    summary: dict[Severity, int] = {s: 0 for s in Severity}
    total_cost = 0.0
    for r in results:
        for f in r.findings:
            if f.validation_status != "filtered":
                summary[f.severity] = summary.get(f.severity, 0) + 1
        total_cost += _usage_cost(r.token_usage, r.model or model)
    if harness_usage:
        total_cost += _usage_cost(harness_usage, harness_model or model)

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
) -> tuple[list[CheckerResult], TokenUsage]:
    """Execute checker agents, then run post-validation.

    Phase 1: Agent execution — all checkers run concurrently under a global
             concurrency cap (config.max_concurrent_agents). No checker
             depends on another's output, so there are no barriers; light
             checkers are scheduled first, citation_claim last.
    Phase 2: Deterministic post-validation (filter obvious false positives)
    Phase 3: Reviewer agent (LLM-based validation of remaining findings)

    Returns (results, harness_usage) where harness_usage is the reviewer
    agent's token usage (for cost accounting).
    """
    from sub_checker.harness.dedup import deduplicate_cross_checker
    from sub_checker.harness.deterministic import run_deterministic_checks
    from sub_checker.harness.reviewer import run_reviewer

    # --- Phase 1: Agent execution (bounded concurrency) ---
    order = {name: i for i, name in enumerate(AGENT_ORDER)}
    scheduled = sorted(agents, key=lambda a: order.get(a.name, len(order)))

    await _notify(
        on_progress, "phase_start", "", {"phase": 1, "agents": [a.name for a in scheduled]}
    )

    semaphore = asyncio.Semaphore(max(1, config.max_concurrent_agents))

    async def run_limited(agent: BaseCheckerAgent) -> CheckerResult:
        async with semaphore:
            return await run_agent_safe(agent, manuscript, config, on_progress)

    results: list[CheckerResult] = list(await asyncio.gather(*[run_limited(a) for a in scheduled]))

    # --- Phase 2: Deterministic post-validation ---
    await _notify(on_progress, "phase_start", "", {"phase": 2, "agents": ["deterministic_check"]})
    await _notify(on_progress, "agent_start", "deterministic_check", {})

    total_before = sum(len(r.findings) for r in results)
    results = run_deterministic_checks(results, manuscript)
    filtered_det = sum(1 for r in results for f in r.findings if f.validation_status == "filtered")
    logger.info(
        "Deterministic post-validation: %d/%d findings filtered", filtered_det, total_before
    )

    await _notify(
        on_progress, "agent_done", "deterministic_check", {"filtered": filtered_det, "elapsed": 0.0}
    )

    # --- Phase 3: Reviewer agent ---
    harness_usage = TokenUsage()
    remaining = total_before - filtered_det
    if remaining > 0:
        await _notify(on_progress, "phase_start", "", {"phase": 3, "agents": ["reviewer"]})
        await _notify(on_progress, "agent_start", "reviewer", {})

        results, harness_usage = await run_reviewer(
            manuscript, results, model=config.reviewer_model or config.model
        )

        confirmed = sum(
            1 for r in results for f in r.findings if f.validation_status == "confirmed"
        )
        filtered_rev = (
            sum(1 for r in results for f in r.findings if f.validation_status == "filtered")
            - filtered_det
        )
        await _notify(
            on_progress,
            "agent_done",
            "reviewer",
            {"confirmed": confirmed, "filtered": filtered_rev, "elapsed": 0.0},
        )

    # --- Cross-checker dedup (after reviewer: confidence scores are final) ---
    deduplicate_cross_checker(results)

    return results, harness_usage
