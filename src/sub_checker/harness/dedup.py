"""Cross-checker deduplication of findings.

Different checkers often surface the same underlying issue (e.g. a wrong DOI
on reference [15] is reported by figure_table, citation_exist, citation_format
AND citation_claim). Showing the same problem four times is noise. This pass
keeps the single highest-confidence instance and filters the rest.

Runs AFTER the reviewer so confidence scores are final. It is deliberately
conservative — it only merges findings that are clearly about the same thing,
and merging only hides duplicates (they keep their data and a note), so a
wrong merge is visible and recoverable.
"""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

from sub_checker.models import CheckerResult, Finding

logger = logging.getLogger("sub_checker.harness.dedup")

# Similarity thresholds for "same issue, different checker".
_SIM_SAME_REF = 0.55  # when both findings name the same reference number
_SIM_NO_REF = 0.80  # when neither names a reference (stricter — less signal)


def _norm(text: str | None) -> str:
    """Normalize a message for comparison (drop punctuation/whitespace)."""
    return re.sub(r"[\s\W]+", "", (text or "").lower())


def _similar(a: Finding, b: Finding) -> float:
    return SequenceMatcher(None, _norm(a.message), _norm(b.message)).ratio()


def _is_duplicate(a: Finding, b: Finding) -> bool:
    """True if a and b (from different checkers) report the same issue."""
    if a.checker == b.checker:
        return False  # within-checker findings are intentionally distinct
    if a.ref_number is not None and a.ref_number == b.ref_number:
        # Same reference — but the same ref can have distinct issues (wrong
        # DOI vs. bibliographic format), so still require message similarity.
        return _similar(a, b) >= _SIM_SAME_REF
    if a.ref_number is None and b.ref_number is None:
        return _similar(a, b) >= _SIM_NO_REF
    return False


def deduplicate_cross_checker(results: list[CheckerResult]) -> int:
    """Filter cross-checker duplicate findings in place. Returns count removed.

    The highest-confidence finding in each duplicate group is kept; the rest
    are marked validation_status="filtered" (hidden from reports).
    """
    active = [f for r in results for f in r.findings if f.validation_status != "filtered"]
    # Highest confidence first so it becomes each group's representative.
    active.sort(key=lambda f: f.confidence, reverse=True)

    kept: list[Finding] = []
    removed = 0
    for f in active:
        match = next((k for k in kept if _is_duplicate(f, k)), None)
        if match is None:
            kept.append(f)
            continue
        f.validation_status = "filtered"
        note = (
            f"[dedup] duplicate of a higher-confidence '{match.checker}' finding "
            f"(conf {match.confidence:.2f})"
        )
        f.validation_note = f"{f.validation_note} | {note}" if f.validation_note else note
        removed += 1
        logger.info(
            "Deduplicated %s finding (kept %s): %.40s",
            f.checker,
            match.checker,
            f.message,
        )

    if removed:
        logger.info("Cross-checker dedup removed %d duplicate finding(s)", removed)
    return removed
