"""Multi-source citation verifier with cross-validation.

Queries PubMed, Semantic Scholar, and Crossref in parallel,
then cross-validates results to produce a confidence score.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from sub_checker.services.crossref import CrossrefClient
from sub_checker.services.pubmed import PubMedClient
from sub_checker.services.semantic_scholar import SemanticScholarClient


@dataclass
class VerifiedReference:
    """Result of multi-source verification for a single reference."""

    ref_number: int
    ref_text: str  # Original reference text from manuscript
    confidence: float  # 0.0 to 1.0
    status: str  # "verified", "likely_valid", "uncertain", "not_found"
    sources_found: list[str]  # e.g. ["pubmed", "crossref", "semantic_scholar"]
    best_match: dict[str, Any] = field(default_factory=dict)
    details: str = ""


def _normalize_title(title: str) -> str:
    """Normalize title for comparison."""
    title = re.sub(r"<[^>]+>", "", title)  # strip HTML tags
    title = re.sub(r"[^\w\s]", "", title.lower())
    return " ".join(title.split())


def _title_similarity(a: str, b: str) -> float:
    """Compare two titles, return 0-1 similarity."""
    na, nb = _normalize_title(a), _normalize_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


def _extract_first_author(ref_text: str) -> str:
    """Extract first author surname from reference text."""
    # Match patterns like "Smith AB," or "Smith A, " or "Smith-Jones AB,"
    m = re.match(r"^(\d+\.\s*)?([A-Z][a-z'-]+)", ref_text.strip())
    return m.group(2) if m else ""


def _extract_year(ref_text: str) -> str:
    """Extract publication year from reference text."""
    years = re.findall(r"\b(?:19|20)\d{2}\b", ref_text)
    return years[-1] if years else ""


def _extract_doi(ref_text: str) -> str:
    """Extract DOI from reference text."""
    m = re.search(r"(?:doi[:\s]*|https?://doi\.org/)(10\.\S+?)\.?\s*$", ref_text, re.I)
    return m.group(1).rstrip(".") if m else ""


def _extract_title_keywords(ref_text: str) -> str:
    """Extract likely title from reference (between author and journal)."""
    # Remove author part (before first period after names)
    parts = ref_text.split(".", 2)
    if len(parts) >= 2:
        candidate = parts[1].strip()
        # Remove trailing journal/year info
        candidate = re.split(r"\b[A-Z][a-z]*\s+(?:Surg|Med|J|Ann|Br|Lancet|Cancer)", candidate)[0]
        return candidate.strip()[:80]
    return ""


def _parse_reference(ref_text: str) -> dict[str, str]:
    """Parse a reference line into components."""
    return {
        "author": _extract_first_author(ref_text),
        "year": _extract_year(ref_text),
        "doi": _extract_doi(ref_text),
        "title_keywords": _extract_title_keywords(ref_text),
    }


async def _query_pubmed(
    pubmed: PubMedClient, author: str, year: str, title_kw: str
) -> list[dict[str, Any]]:
    """Query PubMed, return results."""
    try:
        return await pubmed.search(author=author, year=year, title_keywords=title_kw)
    except Exception:
        return []


async def _query_s2(
    s2: SemanticScholarClient, author: str, year: str, title_kw: str
) -> list[dict[str, Any]]:
    """Query Semantic Scholar, return results."""
    try:
        query = f"{author} {title_kw}".strip()
        return await s2.search(query=query, year=year)
    except Exception:
        return []


async def _query_crossref(
    crossref: CrossrefClient, author: str, year: str, title_kw: str, doi: str
) -> list[dict[str, Any]]:
    """Query Crossref, return results. If DOI available, use direct lookup."""
    try:
        if doi:
            result = await crossref.get_by_doi(doi)
            return [result] if result else []
        return await crossref.search(author=author, title_keywords=title_kw, year=year)
    except Exception:
        return []


def _cross_validate(
    ref_parsed: dict[str, str],
    pubmed_results: list[dict[str, Any]],
    s2_results: list[dict[str, Any]],
    crossref_results: list[dict[str, Any]],
) -> VerifiedReference:
    """Cross-validate results from three sources."""
    sources_found: list[str] = []
    best_match: dict[str, Any] = {}
    best_score = 0.0
    title_kw = ref_parsed["title_keywords"]

    sources: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("pubmed", "pmid", pubmed_results),
        ("semantic_scholar", "doi", s2_results),
        ("crossref", "doi", crossref_results),
    ]

    for source_name, id_key, source_results in sources:
        for r in source_results:
            title = r.get("title", "")
            sim = _title_similarity(title_kw, title) if title_kw else 0.3
            if sim > best_score:
                best_score = sim
                best_match = {"source": source_name, id_key: r.get(id_key), "title": title}
            if sim > 0.4:
                sources_found.append(source_name)
                break

    # Determine confidence and status
    n_sources = len(sources_found)
    if n_sources >= 3:
        confidence = 0.95
        status = "verified"
    elif n_sources == 2:
        confidence = 0.85
        status = "verified"
    elif n_sources == 1:
        confidence = 0.6 + best_score * 0.2
        status = "likely_valid"
    else:
        confidence = best_score * 0.4
        status = "uncertain" if best_score > 0.3 else "not_found"

    details_parts = []
    if sources_found:
        details_parts.append(f"Found in: {', '.join(sources_found)}")
    if best_match:
        details_parts.append(f"Best match: {best_match.get('title', '')[:80]}")
    if not sources_found:
        details_parts.append("Not found in any database (may be very recent or non-indexed)")

    return VerifiedReference(
        ref_number=0,  # set by caller
        ref_text="",  # set by caller
        confidence=round(confidence, 2),
        status=status,
        sources_found=sources_found,
        best_match=best_match,
        details=". ".join(details_parts),
    )


async def _verify_single(
    ref_num: int,
    ref_text: str,
    pubmed: PubMedClient,
    s2: SemanticScholarClient,
    crossref: CrossrefClient,
) -> VerifiedReference:
    """Verify a single reference against all three sources."""
    parsed = _parse_reference(ref_text)

    if not parsed["author"] and not parsed["doi"]:
        return VerifiedReference(
            ref_number=ref_num,
            ref_text=ref_text[:100],
            confidence=0.0,
            status="unparseable",
            sources_found=[],
            details="Could not extract author or DOI from reference text",
        )

    # Query all three sources in parallel (rate limits handled per-client)
    pm_task = _query_pubmed(pubmed, parsed["author"], parsed["year"], parsed["title_keywords"])
    s2_task = _query_s2(s2, parsed["author"], parsed["year"], parsed["title_keywords"])
    cr_task = _query_crossref(
        crossref, parsed["author"], parsed["year"], parsed["title_keywords"], parsed["doi"]
    )

    pm_results, s2_results, cr_results = await asyncio.gather(pm_task, s2_task, cr_task)

    verified = _cross_validate(parsed, pm_results, s2_results, cr_results)
    verified.ref_number = ref_num
    verified.ref_text = ref_text[:100]
    return verified


_BATCH_SIZE = 3  # Process references in batches to avoid overwhelming APIs


async def verify_references(
    reference_lines: list[str],
    pubmed: PubMedClient,
    s2: SemanticScholarClient,
    crossref: CrossrefClient,
) -> list[VerifiedReference]:
    """Verify all references against PubMed, Semantic Scholar, and Crossref.

    Processes in batches of 3 to respect API rate limits while maintaining
    parallelism within each batch.
    """
    results: list[VerifiedReference] = []

    for batch_start in range(0, len(reference_lines), _BATCH_SIZE):
        batch = reference_lines[batch_start : batch_start + _BATCH_SIZE]
        tasks = [
            _verify_single(batch_start + j + 1, ref_text, pubmed, s2, crossref)
            for j, ref_text in enumerate(batch)
        ]
        batch_results = await asyncio.gather(*tasks)
        results.extend(batch_results)

    return results


def format_verification_report(results: list[VerifiedReference]) -> str:
    """Format verification results as a readable report for agent consumption."""
    lines = [
        "--- MULTI-SOURCE REFERENCE VERIFICATION REPORT ---",
        f"Total references: {len(results)}",
        "",
    ]

    verified_count = sum(1 for r in results if r.status == "verified")
    likely_count = sum(1 for r in results if r.status == "likely_valid")
    uncertain_count = sum(1 for r in results if r.status == "uncertain")
    not_found_count = sum(1 for r in results if r.status == "not_found")

    lines.append(
        f"Summary: {verified_count} verified | {likely_count} likely valid | "
        f"{uncertain_count} uncertain | {not_found_count} not found"
    )
    lines.append("")

    for r in results:
        emoji = {"verified": "OK", "likely_valid": "~OK", "uncertain": "??", "not_found": "XX"}
        tag = emoji.get(r.status, r.status)
        lines.append(
            f"[{r.ref_number}] [{tag}] confidence={r.confidence} "
            f"sources={r.sources_found or 'none'}"
        )
        if r.details:
            lines.append(f"    {r.details}")
        if r.status in ("uncertain", "not_found"):
            lines.append(f"    ref: {r.ref_text}")

    lines.append("--- END VERIFICATION REPORT ---")
    return "\n".join(lines)
