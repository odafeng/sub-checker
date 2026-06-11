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
    """Extract first author surname from reference text.

    Handles "Smith AB,", "Smith-Jones AB,", and lowercase particles like
    "van Gijn W," or "de la Portilla F,".
    """
    text = re.sub(r"^\d+\.\s*", "", ref_text.strip())  # strip "12. " numbering
    m = re.match(
        r"^((?:(?:van|von|de|del|der|den|da|di|la|le)\s+){0,2}[A-Z][a-zA-Z'-]+)",
        text,
    )
    return m.group(1) if m else ""


def _extract_year(ref_text: str) -> str:
    """Extract publication year from reference text.

    Page ranges like "2013-2019" fall in the year regex's range, so strip
    number ranges first, then take the FIRST remaining year — in Vancouver
    and Springer styles the publication year precedes page numbers.
    """
    text = re.sub(r"\b\d+\s*[-\u2013]\s*\d+\b", "", ref_text)  # hyphen or en dash
    years = re.findall(r"\b(?:19|20)\d{2}\b", text)
    return years[0] if years else ""


def _extract_doi(ref_text: str) -> str:
    """Extract DOI from reference text (not anchored — DOIs may be followed
    by text like "Accessed 2024" or "[Epub ahead of print]")."""
    m = re.search(r"(?:doi[:\s]*|https?://doi\.org/)(10\.\S+)", ref_text, re.I)
    return m.group(1).rstrip(".,;") if m else ""


def _extract_title_keywords(ref_text: str) -> str:
    """Extract likely title from reference (between author and journal)."""
    text = re.sub(r"^\d+\.\s*", "", ref_text.strip())  # strip "12. " numbering

    # Springer/(YYYY) style: "Heald RJ, Husband EM (1982) The mesorectum..." —
    # the title is the text after the year parenthesis, up to the next period.
    m = re.search(r"\((?:19|20)\d{2}\)\s*(.+)", text)
    if m:
        return m.group(1).split(".")[0].strip()[:80]

    # Vancouver style: "Heald RJ, Husband EM. The mesorectum... Br J Surg. 1982"
    parts = text.split(".", 2)
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
    ref_doi = ref_parsed.get("doi", "").lower()

    sources: list[tuple[str, str, list[dict[str, Any]]]] = [
        ("pubmed", "pmid", pubmed_results),
        ("semantic_scholar", "doi", s2_results),
        ("crossref", "doi", crossref_results),
    ]

    # A DOI lookup that returns the exact DOI is definitive — it must not
    # depend on title-keyword similarity (which can be empty/unparseable).
    doi_confirmed = False
    if ref_doi:
        for source_name, id_key, source_results in sources:
            for r in source_results:
                if (r.get("doi") or "").lower() == ref_doi:
                    doi_confirmed = True
                    if source_name not in sources_found:
                        sources_found.append(source_name)
                    if not best_match:
                        best_match = {
                            "source": source_name,
                            id_key: r.get(id_key),
                            "title": r.get("title", ""),
                        }
                    break

    for source_name, id_key, source_results in sources:
        for r in source_results:
            title = r.get("title", "")
            sim = _title_similarity(title_kw, title) if title_kw else 0.0
            if sim > best_score:
                best_score = sim
                best_match = {"source": source_name, id_key: r.get(id_key), "title": title}
            if sim > 0.55 and source_name not in sources_found:
                sources_found.append(source_name)
                break

    # Determine confidence and status. Multi-source counts scale with the
    # best title similarity so three weak 0.56 matches can't reach 0.95.
    n_sources = len(sources_found)
    if n_sources >= 3:
        confidence = 0.75 + best_score * 0.2
        status = "verified"
    elif n_sources == 2:
        confidence = 0.65 + best_score * 0.2
        status = "verified"
    elif n_sources == 1:
        confidence = 0.6 + best_score * 0.2
        status = "likely_valid"
    else:
        confidence = best_score * 0.4
        status = "uncertain" if best_score > 0.3 else "not_found"
        # No title keywords to compare against, but the queries did return
        # candidates — we can't verify, but "not found" would be wrong too.
        if not title_kw and any(res for _, _, res in sources):
            confidence = 0.3
            status = "uncertain"

    if doi_confirmed:
        confidence = max(confidence, 0.9)
        status = "verified"

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


_MAX_IN_FLIGHT = 8  # references verified concurrently; per-client rate
# limiters and semaphores do the real throttling, so a batch barrier would
# only let the slowest source (S2 at 1 req/s) idle the fast ones.


async def verify_references(
    reference_lines: list[str],
    pubmed: PubMedClient,
    s2: SemanticScholarClient,
    crossref: CrossrefClient,
) -> list[VerifiedReference]:
    """Verify all references against PubMed, Semantic Scholar, and Crossref."""
    in_flight = asyncio.Semaphore(_MAX_IN_FLIGHT)

    async def bounded(ref_num: int, ref_text: str) -> VerifiedReference:
        async with in_flight:
            return await _verify_single(ref_num, ref_text, pubmed, s2, crossref)

    return list(
        await asyncio.gather(
            *(bounded(i + 1, ref_text) for i, ref_text in enumerate(reference_lines))
        )
    )


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
    unparseable_count = sum(1 for r in results if r.status == "unparseable")

    lines.append(
        f"Summary: {verified_count} verified | {likely_count} likely valid | "
        f"{uncertain_count} uncertain | {not_found_count} not found | "
        f"{unparseable_count} unparseable"
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
