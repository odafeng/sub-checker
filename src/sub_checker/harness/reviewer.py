"""Reviewer agent: post-validation of all findings against the manuscript.

An independent Opus agent that reviews every finding produced by the checker
agents, cross-references against the actual manuscript, and either confirms,
downgrades, or filters each finding. This is the LLM-based layer of Phase 3.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import anthropic

from sub_checker.models import CheckerResult, Finding, Manuscript, Severity

logger = logging.getLogger("sub_checker.harness.reviewer")

_SYSTEM_PROMPT = """\
You are a rigorous post-validation reviewer for an academic manuscript checker.

Your job: review EVERY finding produced by the checker agents and determine if
each finding is correct, by cross-referencing against the actual manuscript text.

## Rules

1. You will receive the manuscript text and a list of findings in JSON format.
2. For EACH finding, output a JSON verdict with:
   - "index": the finding's index (0-based)
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


def _build_review_message(
    manuscript: Manuscript,
    results: list[CheckerResult],
) -> str:
    """Build the review prompt with manuscript context and all findings."""
    # Manuscript context (truncated to avoid token overflow)
    header = manuscript.header_text[:500] if manuscript.header_text else ""
    sections = [s.heading for s in manuscript.sections]
    raw_preview = manuscript.raw_text[:3000]

    findings_json: list[dict[str, Any]] = []
    idx = 0
    for result in results:
        for f in result.findings:
            if f.validation_status == "filtered":
                continue  # Skip already-filtered by deterministic checks
            findings_json.append(
                {
                    "index": idx,
                    "checker": f.checker,
                    "severity": f.severity.value,
                    "message": f.message,
                    "location": f.location,
                    "suggestion": f.suggestion,
                }
            )
            idx += 1

    return (
        f"## Manuscript Context\n\n"
        f"Title: {manuscript.title}\n"
        f"Sections: {sections}\n"
        f"Header:\n{header}\n\n"
        f"Text preview (first 3000 chars):\n{raw_preview}\n\n"
        f"Has references: {manuscript.reference_section is not None}\n"
        f"Reference preview: {(manuscript.reference_section or '')[:500]}\n\n"
        f"## Findings to Review ({len(findings_json)} total)\n\n"
        f"```json\n{json.dumps(findings_json, ensure_ascii=False, indent=2)}\n```\n\n"
        f"Review each finding and return a JSON array of verdicts."
    )


async def run_reviewer(
    manuscript: Manuscript,
    results: list[CheckerResult],
    model: str = "claude-opus-4-8",
) -> list[CheckerResult]:
    """Run the reviewer agent to validate all findings.

    Modifies findings in-place with confidence scores and validation status.
    Findings marked as "filtered" by deterministic checks are skipped.
    Returns the same results list (modified).
    """
    # Collect non-filtered findings with their original positions
    finding_map: list[tuple[int, int, Finding]] = []  # (result_idx, finding_idx, finding)
    for ri, result in enumerate(results):
        for fi, finding in enumerate(result.findings):
            if finding.validation_status != "filtered":
                finding_map.append((ri, fi, finding))

    if not finding_map:
        logger.info("No findings to review (all filtered by deterministic checks)")
        return results

    logger.info("Reviewer agent reviewing %d findings with %s...", len(finding_map), model)
    start = time.monotonic()

    client = anthropic.AsyncAnthropic()
    message = _build_review_message(manuscript, results)

    try:
        response = await client.messages.create(
            model=model,
            max_tokens=4096,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": message}],
        )
    except Exception as e:
        logger.error("Reviewer agent failed: %s", e)
        # On failure, leave findings as-is (don't block output)
        return results

    # Parse response
    text = ""
    for block in response.content:
        if block.type == "text":
            text += block.text  # type: ignore[union-attr]

    elapsed = time.monotonic() - start
    logger.info("Reviewer completed in %.1fs, parsing verdicts...", elapsed)

    # Extract JSON from response (may be wrapped in ```json...```)
    json_match = text
    if "```" in text:
        import re

        m = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
        if m:
            json_match = m.group(1)

    try:
        verdicts = json.loads(json_match)
    except json.JSONDecodeError:
        logger.error("Reviewer returned invalid JSON: %s", text[:500])
        return results

    if not isinstance(verdicts, list):
        logger.error("Reviewer returned non-list: %s", type(verdicts))
        return results

    # Apply verdicts
    confirmed = 0
    filtered = 0
    downgraded = 0

    for verdict in verdicts:
        idx = verdict.get("index")
        action = verdict.get("action", "confirm")
        confidence = verdict.get("confidence", 0.5)
        reason = verdict.get("reason", "")

        if not isinstance(idx, int) or idx < 0 or idx >= len(finding_map):
            continue

        _, _, finding = finding_map[idx]
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

    logger.info(
        "Reviewer results: %d confirmed, %d downgraded, %d filtered (of %d)",
        confirmed,
        downgraded,
        filtered,
        len(finding_map),
    )

    return results
