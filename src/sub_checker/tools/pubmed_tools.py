"""Tools for agents to search academic literature (PubMed + Semantic Scholar fallback)."""

from __future__ import annotations

from sub_checker.services.pubmed import PubMedClient
from sub_checker.services.semantic_scholar import SemanticScholarClient


async def search_literature(
    pubmed: PubMedClient,
    s2: SemanticScholarClient,
    author: str,
    year: str,
    title_keywords: str = "",
) -> str:
    """Search PubMed first, fall back to Semantic Scholar if no results."""
    # Try PubMed
    results = await pubmed.search(author=author, year=year, title_keywords=title_keywords)
    if results:
        lines = [f"Found {len(results)} PubMed result(s):"]
        for r in results[:5]:
            lines.append(f"  PMID: {r['pmid']} | {r['title'][:120]}")
        return "\n".join(lines)

    # Fallback to Semantic Scholar
    query = f"{author} {title_keywords}".strip()
    s2_results = await s2.search(query=query, year=year)
    if s2_results:
        lines = [f"Not found on PubMed. Found {len(s2_results)} Semantic Scholar result(s):"]
        for r in s2_results[:5]:
            authors_str = ", ".join(r["authors"][:3])
            if len(r["authors"]) > 3:
                authors_str += " et al."
            pid = r["paperId"][:8]
            doi_info = f" | DOI: {r['doi']}" if r.get("doi") else ""
            lines.append(f"  S2:{pid} | {r['title'][:100]} | {authors_str}{doi_info}")
        return "\n".join(lines)

    return (
        f"No results found on PubMed or Semantic Scholar for "
        f"author='{author}', year='{year}', keywords='{title_keywords}'."
    )


async def get_abstract(
    pubmed: PubMedClient,
    s2: SemanticScholarClient,
    paper_id: str,
) -> str:
    """Get abstract by PMID or Semantic Scholar paper ID."""
    # If it looks like a PMID (numeric), try PubMed first
    if paper_id.isdigit():
        abstract = await pubmed.get_abstract(paper_id)
        if abstract and len(abstract) > 50:
            return f"Abstract (PMID {paper_id}):\n{abstract}"

    # Try Semantic Scholar (accepts S2 ID, DOI:xxx, PMID:xxx)
    s2_id = paper_id
    if paper_id.isdigit():
        s2_id = f"PMID:{paper_id}"

    paper = await s2.get_paper(s2_id)
    if paper and paper.get("abstract"):
        source = "Semantic Scholar"
        title = paper["title"]
        return f'Abstract ({source}, "{title}"):\n{paper["abstract"]}'

    if paper and not paper.get("abstract"):
        return (
            f"Paper found ({paper['title']}) but no abstract available. "
            f"Authors: {', '.join(paper['authors'][:5])}. Year: {paper.get('year')}."
        )

    return f"No abstract found for paper ID '{paper_id}' on PubMed or Semantic Scholar."


TOOL_SEARCH_LITERATURE = {
    "name": "search_literature",
    "description": (
        "Search for an academic paper by author, year, and optional title keywords. "
        "Searches PubMed first, then falls back to Semantic Scholar for broader coverage "
        "(CS, engineering, non-biomedical fields)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "author": {
                "type": "string",
                "description": "First author surname (e.g. 'Smith', 'Zhang')",
            },
            "year": {
                "type": "string",
                "description": "Publication year (e.g. '2023')",
            },
            "title_keywords": {
                "type": "string",
                "description": "Keywords from the paper title to narrow search",
            },
        },
        "required": ["author", "year"],
    },
}

TOOL_GET_ABSTRACT = {
    "name": "get_abstract",
    "description": (
        "Get the abstract of a paper by its ID. "
        "Accepts: PubMed ID (numeric, e.g. '12345678'), "
        "Semantic Scholar ID (e.g. 'S2:abc12345'), "
        "or DOI (e.g. 'DOI:10.1234/xxx')."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "paper_id": {
                "type": "string",
                "description": "Paper identifier (PMID, S2 paper ID, or DOI:xxx)",
            }
        },
        "required": ["paper_id"],
    },
}

# Keep old names for backward compat
TOOL_SEARCH_PUBMED = TOOL_SEARCH_LITERATURE
