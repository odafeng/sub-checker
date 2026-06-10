"""Reviewer agent: post-validation of all findings against the manuscript.

An independent Opus agent that reviews every finding produced by the checker
agents, cross-references against the actual manuscript, and either confirms,
downgrades, or filters each finding. This is the LLM-based layer of Phase 3.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import anthropic

from sub_checker.models import CheckerResult, Finding, Manuscript, Severity, TokenUsage

logger = logging.getLogger("sub_checker.harness.reviewer")

# Findings per review request. Keeps each verdict JSON well within max_tokens
# so a truncated response can't silently drop the whole batch.
_BATCH_SIZE = 25
_MAX_TOKENS = 8192
_MANUSCRIPT_PREVIEW_CHARS = 8000

_SYSTEM_PROMPT = """\
You are a rigorous post-validation reviewer for an academic manuscript checker.

Your job: review EVERY finding produced by the checker agents and determine if
each finding is correct, by cross-referencing against the actual manuscript text.

## Rules

1. You will receive the manuscript text and a list of findings in JSON format.
2. For EACH finding, output a JSON verdict with:
   - "index": the finding's index (as given in the input)
   - "action": one of "confirm", "downgrade", "filter"
   - "confidence": 0.0 to 1.0 (your confidence the finding is valid)
   - "reason": brief explanation (1-2 sentences)

3. Use "confirm" for findings that are correct and actionable.
4. Use "downgrade" for findings that have some merit but are exaggerated,
   imprecise, or should be info-level instead of error/warning.
5. Use "filter" for findings that are factually wrong, self-contradictory,
   or based on incorrect premises.

## Common false positive patterns to watch for

- Claiming a date is in the future when it is actually in the past
- Claiming a section is missing when its content is in sub-sections
- Claiming citation format inconsistency when all examples use the same format
- Claiming a reference is not cited when it appears in a different section
- Assuming a specific journal format when no target journal was specified
- Flagging standalone heading words (e.g., "Methods") as misplaced text
- Reporting Word auto-numbering as missing reference numbering

## Output format

Return a JSON array of verdicts, one per finding. Example:
```json
[
  {"index": 0, "action": "confirm", "confidence": 0.95, "reason": "IRB number is indeed a placeholder"},
  {"index": 1, "action": "filter", "confidence": 0.1, "reason": "Nov 2025 is past, not future"},
  {"index": 2, "action": "downgrade", "confidence": 0.5, "reason": "Minor style preference, not an error"}
]
```

IMPORTANT: Review ALL findings. Do not skip any. Output ONLY the JSON array."""


def _manuscript_context(manuscript: Manuscript) -> str:
    """Shared manuscript context block (truncated to avoid token overflow)."""
    header = manuscript.header_text[:500] if manuscript.header_text else ""
    sections = [s.heading for s in manuscript.sections]
    raw_preview = manuscript.raw_text[:_MANUSCRIPT_PREVIEW_CHARS]

    return (
        f"## Manuscript Context\n\n"
        f"Title: {manuscript.title}\n"
        f"Sections: {sections}\n"
        f"Header:\n{header}\n\n"
        f"Text preview (first {_MANUSCRIPT_PREVIEW_CHARS} chars):\n{raw_preview}\n\n"
        f"Has references: {manuscript.reference_section is not None}\n"
        f"Reference preview: {(manuscript.reference_section or '')[:500]}\n"
    )


def _build_review_message(
    context: str,
    batch: list[tuple[int, Finding]],
) -> str:
    """Build the review prompt for one batch of (global_index, finding)."""
    findings_json: list[dict[str, Any]] = [
        {
            "index": idx,
            "checker": f.checker,
            "severity": f.severity.value,
            "message": f.message,
            "location": f.location,
            "suggestion": f.suggestion,
        }
        for idx, f in batch
    ]

    return (
        f"{context}\n"
        f"## Findings to Review ({len(findings_json)} total)\n\n"
        f"```json\n{json.dumps(findings_json, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Review each finding and return a JSON array of verdicts."
    )


def _parse_verdicts(text: str) -> list[dict[str, Any]]:
    """Extract the verdict JSON array from the response text."""
    json_match = text
    if "```" in text:
        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            json_match = m.group(1)

    try:
        verdicts = json.loads(json_match)
    except json.JSONDecodeError:
        logger.error("Reviewer returned invalid JSON: %s", text[:500])
        return []

    if not isinstance(verdicts, list):
        logger.error("Reviewer returned non-list: %s", type(verdicts))
        return []
    return verdicts


async def run_reviewer(
    manuscript: Manuscript,
    results: list[CheckerResult],
    model: str = "claude-opus-4-8",
) -> tuple[list[CheckerResult], TokenUsage]:
    """Run the reviewer agent to validate all findings.

    Modifies findings in-place with confidence scores and validation status.
    Findings marked as "filtered" by deterministic checks are skipped.
    Findings are reviewed in batches so one truncated/invalid response only
    affects its own batch.
    Returns (results, token_usage).
    """
    usage = TokenUsage()

    # Collect non-filtered findings, indexed globally
    findings: list[Finding] = [
        f for result in results for f in result.findings if f.validation_status != "filtered"
    ]

    if not findings:
        logger.info("No findings to review (all filtered by deterministic checks)")
        return results, usage

    logger.info("Reviewer agent reviewing %d findings with %s...", len(findings), model)
    start = time.monotonic()

    client = anthropic.AsyncAnthropic()
    context = _manuscript_context(manuscript)

    confirmed = 0
    filtered = 0
    downgraded = 0

    for batch_start in range(0, len(findings), _BATCH_SIZE):
        batch = [
            (batch_start + j, f)
            for j, f in enumerate(findings[batch_start : batch_start + _BATCH_SIZE])
        ]
        message = _build_review_message(context, batch)

        try:
            response = await client.messages.create(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": message}],
            )
        except Exception as e:
            logger.error("Reviewer agent failed on batch %d: %s", batch_start, e)
            continue  # leave this batch's findings as-is, don't block output

        usage.input_tokens += response.usage.input_tokens
        usage.output_tokens += response.usage.output_tokens
        usage.cache_creation_input_tokens += response.usage.cache_creation_input_tokens or 0
        usage.cache_read_input_tokens += response.usage.cache_read_input_tokens or 0

        if response.stop_reason == "max_tokens":
            logger.warning(
                "Reviewer response truncated (max_tokens) on batch %d; verdicts may be incomplete",
                batch_start,
            )

        text = "".join(
            block.text  # type: ignore[union-attr]
            for block in response.content
            if block.type == "text"
        )

        for verdict in _parse_verdicts(text):
            idx = verdict.get("index")
            action = verdict.get("action", "confirm")
            confidence = verdict.get("confidence", 0.5)
            reason = verdict.get("reason", "")

            if not isinstance(idx, int) or idx < 0 or idx >= len(findings):
                continue

            finding = findings[idx]
            finding.confidence = float(confidence)
            finding.validation_note = f"[reviewer] {reason}"

            if action == "filter":
                finding.validation_status = "filtered"
                finding.confidence = min(finding.confidence, 0.1)
                filtered += 1
            elif action == "downgrade":
                finding.validation_status = "downgraded"
                finding.severity = Severity.INFO
                downgraded += 1
            else:
                finding.validation_status = "confirmed"
                confirmed += 1

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
