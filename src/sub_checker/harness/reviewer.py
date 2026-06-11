"""Reviewer agent: post-validation of all findings against the manuscript.

An independent agent that reviews every finding produced by the checker
agents and either confirms, downgrades, or filters each one. Unlike the
checkers it is adversarial: its job is to disprove findings.

The reviewer is agentic — it has read_section / search_text /
get_reference_list tools so it can verify each finding against the actual
manuscript text instead of guessing from a truncated preview. Verdicts are
returned through a submit_verdicts tool call (with a text-JSON fallback).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

import anthropic

from sub_checker.agents.base import set_message_cache_breakpoint, supports_adaptive_thinking
from sub_checker.models import CheckerResult, Finding, Manuscript, Severity, TokenUsage
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    get_reference_list,
    read_section,
    search_text,
)

logger = logging.getLogger("sub_checker.harness.reviewer")

# Findings per review conversation. Keeps each verdict set small enough that
# one bad response only affects its own batch.
_BATCH_SIZE = 25
_MAX_TOKENS = 8192
_MAX_ITERATIONS = 12  # tool-use rounds per batch before forcing a verdict
_MAX_CONCURRENT_BATCHES = 3  # batches reviewed in parallel after the first
_MANUSCRIPT_PREVIEW_CHARS = 4000

_SUBMIT_VERDICTS_TOOL = {
    "name": "submit_verdicts",
    "description": (
        "Submit your final verdict for every finding in this batch. "
        "Call this exactly once, after you have verified the findings "
        "against the manuscript."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "verdicts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "index": {
                            "type": "integer",
                            "description": "The finding's index as given in the input",
                        },
                        "action": {
                            "type": "string",
                            "enum": ["confirm", "downgrade", "filter"],
                        },
                        "confidence": {
                            "type": "number",
                            "description": "0.0-1.0, your confidence the finding is valid",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation (1-2 sentences)",
                        },
                    },
                    "required": ["index", "action", "confidence", "reason"],
                },
            }
        },
        "required": ["verdicts"],
    },
}

_SYSTEM_PROMPT = """\
You are a rigorous post-validation reviewer for an academic manuscript checker.

Your job: review EVERY finding produced by the checker agents and determine if
each finding is correct, by cross-referencing against the actual manuscript.

## Tools

You have direct access to the manuscript:
- read_section: read any section in full
- search_text: find where a phrase/keyword appears
- get_reference_list: read the full reference list

A short text preview is included below for orientation, but it is TRUNCATED.
Before you "filter" any finding, verify it against the actual manuscript with
these tools — do not judge from the preview alone. A wrongly filtered real
finding is worse than a confirmed false positive (the user can dismiss noise,
but never sees what you filtered).

## Verdicts

For EACH finding, decide:
- "confirm": correct and actionable
- "downgrade": some merit but exaggerated, imprecise, or should be info-level
- "filter": factually wrong, self-contradictory, or based on incorrect
  premises — only after tool-verified evidence

Findings already marked validation_status="downgraded" were flagged by
deterministic heuristics as probably wrong — double-check those specifically.

## Common false positive patterns to watch for

- Claiming a date is in the future when it is actually in the past
- Claiming a section is missing when its content is in sub-sections
- Claiming citation format inconsistency when all examples use the same format
- Claiming a reference is not cited when it appears in a different section
- Assuming a specific journal format when no target journal was specified
- Flagging standalone heading words (e.g., "Methods") as misplaced text
- Reporting Word auto-numbering as missing reference numbering

## Output

When you have reviewed all findings, call submit_verdicts ONCE with a verdict
for EVERY finding in the batch. Do not skip any."""


def _manuscript_context(manuscript: Manuscript) -> str:
    """Orientation context; the reviewer uses tools for anything beyond this."""
    sections = [s.heading for s in manuscript.sections]
    return (
        f"## Manuscript Context\n\n"
        f"Title: {manuscript.title}\n"
        f"Sections: {sections}\n"
        f"Has references: {manuscript.reference_section is not None}\n\n"
        f"Text preview (TRUNCATED at {_MANUSCRIPT_PREVIEW_CHARS} chars — "
        f"use tools for the rest):\n"
        f"{manuscript.raw_text[:_MANUSCRIPT_PREVIEW_CHARS]}\n"
    )


def _build_review_message(context: str, batch: list[tuple[int, Finding]]) -> str:
    """Build the review prompt for one batch of (global_index, finding)."""
    findings_json: list[dict[str, Any]] = [
        {
            "index": idx,
            "checker": f.checker,
            "severity": f.severity.value,
            "message": f.message,
            "location": f.location,
            "suggestion": f.suggestion,
            "validation_status": f.validation_status,
            "validation_note": f.validation_note,
        }
        for idx, f in batch
    ]

    return (
        f"{context}\n"
        f"## Findings to Review ({len(findings_json)} total)\n\n"
        f"```json\n{json.dumps(findings_json, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Verify each finding against the manuscript (use your tools), then "
        f"call submit_verdicts with a verdict for every finding."
    )


def _parse_text_verdicts(text: str) -> list[dict[str, Any]]:
    """Fallback: extract a verdict JSON array from plain response text."""
    json_match = text
    if "```" in text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            json_match = m.group(1)
    try:
        verdicts = json.loads(json_match)
    except json.JSONDecodeError:
        return []
    return verdicts if isinstance(verdicts, list) else []


async def _review_batch(
    client: anthropic.AsyncAnthropic,
    model: str,
    manuscript: Manuscript,
    context: str,
    batch: list[tuple[int, Finding]],
    usage: TokenUsage,
) -> list[dict[str, Any]]:
    """Run one agentic review conversation; returns the verdict list."""
    tools = [TOOL_READ_SECTION, TOOL_SEARCH_TEXT, TOOL_GET_REFERENCE_LIST, _SUBMIT_VERDICTS_TOOL]
    tools = json.loads(json.dumps(tools))  # deep copy before adding cache marker
    tools[-1]["cache_control"] = {"type": "ephemeral"}
    system_blocks = [
        {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    messages: list[dict[str, Any]] = [
        {
            "role": "user",
            "content": [{"type": "text", "text": _build_review_message(context, batch)}],
        }
    ]

    verdicts: list[dict[str, Any]] = []

    extra: dict[str, Any] = {}
    if supports_adaptive_thinking(model):
        extra["thinking"] = {"type": "adaptive"}

    for iteration in range(1, _MAX_ITERATIONS + 1):
        set_message_cache_breakpoint(messages)  # type: ignore[arg-type]
        response = await client.messages.create(
            model=model,
            max_tokens=_MAX_TOKENS,
            system=system_blocks,  # type: ignore[arg-type]
            tools=tools,
            messages=messages,  # type: ignore[arg-type]
            **extra,
        )

        usage.input_tokens += response.usage.input_tokens
        usage.output_tokens += response.usage.output_tokens
        usage.cache_creation_input_tokens += response.usage.cache_creation_input_tokens or 0
        usage.cache_read_input_tokens += response.usage.cache_read_input_tokens or 0

        if response.stop_reason == "max_tokens":
            logger.warning("Reviewer response truncated (max_tokens) on iteration %d", iteration)

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            tool_input = block.input if isinstance(block.input, dict) else {}
            if block.name == "submit_verdicts":
                submitted = tool_input.get("verdicts", [])
                if isinstance(submitted, list):
                    verdicts.extend(submitted)
                    result = f"Recorded {len(submitted)} verdicts."
                else:
                    result = "Invalid verdicts payload: expected an array."
            elif block.name == "read_section":
                result = read_section(manuscript, str(tool_input.get("section_name", "")))
            elif block.name == "search_text":
                result = search_text(manuscript, str(tool_input.get("query", "")))
            elif block.name == "get_reference_list":
                result = get_reference_list(manuscript)
            else:
                result = f"Unknown tool: {block.name}"
            tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})

        if verdicts:
            return verdicts

        if not tool_results:
            # No tool call — the model may have answered with raw JSON text
            text = "".join(
                block.text  # type: ignore[union-attr]
                for block in response.content
                if block.type == "text"
            )
            return _parse_text_verdicts(text)

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": tool_results})

    logger.warning("Reviewer hit max iterations (%d) without verdicts", _MAX_ITERATIONS)
    return verdicts


async def run_reviewer(
    manuscript: Manuscript,
    results: list[CheckerResult],
    model: str = "claude-opus-4-8",
) -> tuple[list[CheckerResult], TokenUsage]:
    """Run the reviewer agent to validate all findings.

    Modifies findings in-place with confidence scores and validation status.
    Findings marked as "filtered" by deterministic checks are skipped;
    findings "downgraded" by deterministic heuristics are re-reviewed.
    Findings are processed in batches so one bad response only affects its
    own batch. Returns (results, token_usage).
    """
    usage = TokenUsage()

    # Collect findings that still need review: unvalidated ones and those
    # downgraded by deterministic heuristics. Pre-confirmed findings (e.g.
    # harness crash/incomplete notices) and filtered ones are skipped.
    findings: list[Finding] = [
        f
        for result in results
        for f in result.findings
        if f.validation_status in ("", "downgraded")
    ]

    if not findings:
        logger.info("No findings to review (all filtered by deterministic checks)")
        return results, usage

    logger.info("Reviewer agent reviewing %d findings with %s...", len(findings), model)
    start = time.monotonic()

    context = _manuscript_context(manuscript)

    async def process_batch(
        client: anthropic.AsyncAnthropic,
        batch_start: int,
        batch: list[tuple[int, Finding]],
    ) -> tuple[int, int, int]:
        """Review one batch and apply its verdicts. Returns counts."""
        try:
            verdicts = await _review_batch(client, model, manuscript, context, batch, usage)
        except Exception as e:
            logger.error("Reviewer agent failed on batch %d: %s", batch_start, e)
            return (0, 0, 0)  # leave this batch's findings as-is

        if not verdicts:
            logger.warning("Reviewer returned no verdicts for batch %d", batch_start)
            return (0, 0, 0)

        confirmed = downgraded = filtered = 0
        batch_end = batch_start + len(batch)
        for verdict in verdicts:
            if not isinstance(verdict, dict):
                continue
            idx = verdict.get("index")
            action = verdict.get("action", "confirm")
            confidence = verdict.get("confidence", 0.5)
            reason = verdict.get("reason", "")

            # Strict bounds: a verdict may only touch THIS batch's findings.
            # A model returning batch-local indices (0..N) for a later batch
            # must not silently overwrite earlier batches' verdicts.
            if not isinstance(idx, int) or not (batch_start <= idx < batch_end):
                logger.warning(
                    "Reviewer verdict index %r outside batch [%d, %d) — skipped",
                    idx,
                    batch_start,
                    batch_end,
                )
                continue

            finding = findings[idx]
            try:
                finding.confidence = float(confidence)
            except (TypeError, ValueError):
                finding.confidence = 0.5
            finding.validation_note = f"[reviewer] {reason}"

            if action == "filter":
                finding.validation_status = "filtered"
                finding.confidence = min(finding.confidence, 0.1)
                filtered += 1
            elif action == "downgrade":
                finding.validation_status = "downgraded"
                if finding.original_severity is None:
                    finding.original_severity = finding.severity
                finding.severity = Severity.INFO
                downgraded += 1
            else:
                finding.validation_status = "confirmed"
                # If a deterministic heuristic downgraded this finding but the
                # reviewer verified it's real, restore its original severity.
                if finding.original_severity is not None:
                    finding.severity = finding.original_severity
                    finding.original_severity = None
                confirmed += 1
        return (confirmed, downgraded, filtered)

    batches = [
        (
            batch_start,
            [
                (batch_start + j, f)
                for j, f in enumerate(findings[batch_start : batch_start + _BATCH_SIZE])
            ],
        )
        for batch_start in range(0, len(findings), _BATCH_SIZE)
    ]

    async with anthropic.AsyncAnthropic() as client:
        # First batch alone to warm the system+tools prompt cache, then the
        # remaining batches concurrently (each is an independent conversation).
        totals = [await process_batch(client, *batches[0])]
        if len(batches) > 1:
            sem = asyncio.Semaphore(_MAX_CONCURRENT_BATCHES)

            async def bounded(bs: int, b: list[tuple[int, Finding]]) -> tuple[int, int, int]:
                async with sem:
                    return await process_batch(client, bs, b)

            totals.extend(await asyncio.gather(*(bounded(bs, b) for bs, b in batches[1:])))

    confirmed = sum(t[0] for t in totals)
    downgraded = sum(t[1] for t in totals)
    filtered = sum(t[2] for t in totals)

    elapsed = time.monotonic() - start
    logger.info(
        "Reviewer results: %d confirmed, %d downgraded, %d filtered (of %d) in %.1fs",
        confirmed,
        downgraded,
        filtered,
        len(findings),
        elapsed,
    )

    return results, usage
