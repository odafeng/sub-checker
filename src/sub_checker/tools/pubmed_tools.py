"""Tools for agents to query PubMed."""

from __future__ import annotations

from sub_checker.services.pubmed import PubMedClient


async def search_pubmed(
    client: PubMedClient, author: str, year: str, title_keywords: str = ""
) -> str:
    """Search PubMed for a paper by author, year, and optional title keywords."""
    results = await client.search(author=author, year=year, title_keywords=title_keywords)
    if not results:
        return f"No PubMed results found for author='{author}', year='{year}', keywords='{title_keywords}'."
    lines = [f"Found {len(results)} result(s):"]
    for r in results[:5]:
        lines.append(f"  PMID: {r['pmid']} | {r['title'][:100]}")
    return "\n".join(lines)


async def get_abstract(client: PubMedClient, pmid: str) -> str:
    """Get the abstract of a paper by its PMID."""
    abstract = await client.get_abstract(pmid)
    if not abstract:
        return f"No abstract found for PMID {pmid}."
    return f"Abstract (PMID {pmid}):\n{abstract}"


TOOL_SEARCH_PUBMED = {
    "name": "search_pubmed",
    "description": "Search PubMed for a paper by author surname, publication year, and optional title keywords.",
    "input_schema": {
        "type": "object",
        "properties": {
            "author": {
                "type": "string",
                "description": "First author surname",
            },
            "year": {
                "type": "string",
                "description": "Publication year",
            },
            "title_keywords": {
                "type": "string",
                "description": "Optional keywords from the paper title",
            },
        },
        "required": ["author", "year"],
    },
}

TOOL_GET_ABSTRACT = {
    "name": "get_abstract",
    "description": "Get the abstract text of a paper by its PubMed ID (PMID).",
    "input_schema": {
        "type": "object",
        "properties": {
            "pmid": {
                "type": "string",
                "description": "PubMed ID",
            }
        },
        "required": ["pmid"],
    },
}
