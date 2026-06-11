"""Deterministic post-validation checks for agent findings.

These checks use date math and citation cross-referencing to catch obvious
false positives that no LLM should be needed for.

Validation strategy:
- Structured claim fields (claim_type / claimed_date / ref_number, set by the
  agent via add_finding) are checked first — facts, not prose.
- For findings without structured fields, regex parsing of the message is the
  fallback.
- Checks built on exact data (regex scan of the actual manuscript text) may
  "filter"; checks built on heuristics (reference count by line) only
  "downgrade", leaving the final call to the LLM reviewer. A deterministic
  check that wrongly deletes a real finding is a systematic error — fail safe.

Each check returns a list of (finding_index, action, reason) tuples.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from sub_checker.models import CheckerResult, Finding, Manuscript, Severity
from sub_checker.tools.manuscript_tools import count_references, extract_citation_numbers

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _parse_claimed_date(claimed: str) -> datetime | None:
    """Parse 'YYYY' or 'YYYY-MM' into a datetime (first day of period)."""
    m = re.match(r"^\s*(\d{4})(?:-(\d{1,2}))?\s*$", claimed)
    if not m:
        return None
    year = int(m.group(1))
    month = int(m.group(2)) if m.group(2) else 1
    if not (1 <= month <= 12 and 1900 <= year <= 2200):
        return None
    return datetime(year, month, 1, tzinfo=UTC)


def validate_date_claims(
    findings: list[Finding], today: datetime | None = None
) -> list[tuple[int, str, str]]:
    """Check findings that claim a date is in the future.

    Returns (index, action, reason) where action is "filter" or "downgrade".
    """
    today = today or datetime.now(UTC)
    actions: list[tuple[int, str, str]] = []

    for i, f in enumerate(findings):
        # Structured path: the agent told us exactly which date it means
        if f.claim_type == "future_date" and f.claimed_date:
            claimed = _parse_claimed_date(f.claimed_date)
            if claimed and claimed <= today:
                actions.append(
                    (
                        i,
                        "filter",
                        f"{f.claimed_date} is not in the future "
                        f"(today={today.strftime('%Y-%m-%d')})",
                    )
                )
            continue

        # Fallback: parse the finding's prose
        msg = (f.message or "") + " " + (f.suggestion or "")
        # Look for patterns like "November 2025 是未來日期" or "future date"
        future_match = re.search(
            r"((?:January|February|March|April|May|June|July|August|September|"
            r"October|November|December)\s+(\d{4}))\s*.{0,30}(?:未來|future)",
            msg,
            re.IGNORECASE,
        )
        if future_match:
            year = int(future_match.group(2))
            month_name = future_match.group(1).split()[0]
            month = _MONTHS.get(month_name.lower(), 1)
            claimed_date = datetime(year, month, 1, tzinfo=UTC)
            if claimed_date <= today:
                actions.append(
                    (
                        i,
                        "filter",
                        f"{future_match.group(1)} is in the past "
                        f"(today={today.strftime('%Y-%m-%d')})",
                    )
                )

        # Also check "YYYY 是未來" patterns
        year_future = re.search(r"(\d{4})\s*.{0,15}(?:未來|future)", msg, re.IGNORECASE)
        if year_future and not future_match:
            year = int(year_future.group(1))
            if year <= today.year:
                actions.append(
                    (
                        i,
                        "filter",
                        f"Year {year} is not in the future (today={today.strftime('%Y-%m-%d')})",
                    )
                )

    return actions


def _extract_ref_number(f: Finding, pattern: str) -> int | None:
    """Get the reference number for a finding: structured field first, regex fallback."""
    if f.ref_number is not None:
        return f.ref_number
    m = re.search(pattern, (f.message or "").lower(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def validate_citation_numbers(
    findings: list[Finding], manuscript: Manuscript
) -> list[tuple[int, str, str]]:
    """Cross-check citation-related findings against deterministic scan.

    Catches false positives like "reference [23] not cited" when regex
    confirms it IS cited.
    """
    cited = extract_citation_numbers(manuscript.body_text or manuscript.raw_text)
    ref_count = count_references(manuscript.reference_section)
    actions: list[tuple[int, str, str]] = []

    for i, f in enumerate(findings):
        msg = (f.message or "").lower()
        is_uncited_claim = f.claim_type == "uncited_reference" or re.search(
            r"(?:reference|參考文獻)\s*\[?\d+\]?\s*(?:not cited|未.*引用|未被引用)", msg
        )
        is_missing_claim = f.claim_type == "missing_reference" or re.search(
            r"(?:citation|引用)\s*\[?\d+\]?\s*(?:not in|missing|缺失|不存在)", msg
        )

        # "reference [X] is never cited in the text"
        # The cited-number set comes from a regex scan of the full manuscript
        # text — exact data, so a contradiction justifies filtering.
        if is_uncited_claim:
            num = _extract_ref_number(
                f, r"(?:reference|參考文獻)\s*\[?(\d+)\]?\s*(?:not cited|未.*引用|未被引用)"
            )
            if num is not None and num in cited:
                actions.append(
                    (
                        i,
                        "filter",
                        f"Reference [{num}] IS cited in text (deterministic scan confirms)",
                    )
                )
                continue

        # "citation [X] is not in the reference list"
        # ref_count is a line-count heuristic (wrapped/multi-paragraph entries
        # skew it), so only downgrade — the reviewer makes the final call.
        if is_missing_claim:
            num = _extract_ref_number(
                f, r"(?:citation|引用)\s*\[?(\d+)\]?\s*(?:not in|missing|缺失|不存在)"
            )
            if num is not None and 1 <= num <= ref_count:
                actions.append(
                    (
                        i,
                        "downgrade",
                        f"Reference list has ~{ref_count} entries (by line count), "
                        f"so [{num}] likely exists — needs reviewer confirmation",
                    )
                )

    return actions


def validate_self_consistency(
    findings: list[Finding],
) -> list[tuple[int, str, str]]:
    """Check if a finding's message contradicts its own evidence.

    E.g., "X uses underscores, but Y also uses underscores" → self-contradicting.
    """
    actions: list[tuple[int, str, str]] = []

    for i, f in enumerate(findings):
        msg = f.message or ""
        suggestion = f.suggestion or ""
        combined = msg + " " + suggestion

        # Pattern: "X uses A, but Y also uses A" -> not inconsistent
        inconsistency_match = f.claim_type == "inconsistency" or re.search(
            r"(?:不一致|inconsisten|混用|mixed)",
            combined,
            re.IGNORECASE,
        )
        if inconsistency_match:
            # Check if all cited examples actually use the same pattern
            underscores = re.findall(r"[A-Za-z]+_[A-Za-z]+", combined)
            if len(underscores) >= 2:
                # All examples use underscores → not actually inconsistent
                actions.append(
                    (
                        i,
                        "downgrade",
                        f"All cited examples use the same pattern: {underscores[:4]}",
                    )
                )

    return actions


def run_deterministic_checks(
    results: list[CheckerResult], manuscript: Manuscript
) -> list[CheckerResult]:
    """Run all deterministic post-validation checks.

    Modifies findings in-place: filtered findings get validation_status="filtered",
    downgraded findings get validation_status="downgraded".
    Returns the same results list (modified).
    """
    for result in results:
        all_actions: list[tuple[int, str, str]] = []
        all_actions.extend(validate_date_claims(result.findings))
        all_actions.extend(validate_citation_numbers(result.findings, manuscript))
        all_actions.extend(validate_self_consistency(result.findings))

        for idx, action, reason in all_actions:
            if 0 <= idx < len(result.findings):
                finding = result.findings[idx]
                finding.validation_note = f"[deterministic] {reason}"
                if action == "filter":
                    finding.validation_status = "filtered"
                    finding.confidence = 0.0
                elif action == "downgrade":
                    finding.validation_status = "downgraded"
                    if finding.original_severity is None:
                        finding.original_severity = finding.severity
                    finding.severity = Severity.INFO
                    finding.confidence = 0.3

    return results
