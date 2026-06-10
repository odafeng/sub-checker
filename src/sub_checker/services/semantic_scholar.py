"""Semantic Scholar API client — fallback for papers not found on PubMed.

Rate limit: ~100 req/sec for unauthenticated, but practically 1 req/sec is safe.
Retries on 429/5xx with exponential backoff.
"""

from __future__ import annotations

from typing import Any

import httpx

from sub_checker.services.http_client import RateLimitedClient

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"

_FIELDS = "title,year,authors,abstract,externalIds"


def _parse_paper(p: dict[str, Any]) -> dict[str, Any]:
    """Convert an S2 paper record into our normalized paper dict."""
    authors = [a.get("name", "") for a in (p.get("authors") or [])]
    ext_ids = p.get("externalIds") or {}
    return {
        "paperId": p.get("paperId", ""),
        "title": p.get("title", ""),
        "year": p.get("year"),
        "authors": authors,
        "abstract": p.get("abstract") or "",
        "doi": ext_ids.get("DOI", ""),
        "pmid": ext_ids.get("PubMed", ""),
    }


class SemanticScholarClient(RateLimitedClient):
    service_name = "semantic_scholar"

    def __init__(self, max_concurrent: int = 1):
        super().__init__(
            min_interval=1.0,  # S2 rate limit is strict for unauthenticated
            max_concurrent=max_concurrent,
            headers={"User-Agent": "sub-checker/0.1 (academic manuscript checker)"},
        )
        self._cache: dict[str, Any] = {}

    async def search(
        self, query: str, year: str = "", max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search Semantic Scholar. Returns list of paper dicts."""
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        params: dict[str, str] = {
            "query": query,
            "limit": str(max_results),
            "fields": _FIELDS,
        }
        if year:
            params["year"] = year
        try:
            resp = await self._rate_limited_get(S2_SEARCH_URL, params)
        except httpx.HTTPError:
            return []

        results = [_parse_paper(p) for p in resp.json().get("data", [])]
        self._cache[cache_key] = results
        return results

    async def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """Get paper details by Semantic Scholar paper ID, DOI, or PMID."""
        cache_key = f"paper:{paper_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = await self._rate_limited_get(
                f"{S2_PAPER_URL}/{paper_id}",
                params={"fields": _FIELDS},
            )
        except httpx.HTTPError:
            return None

        result = _parse_paper(resp.json())
        self._cache[cache_key] = result
        return result
