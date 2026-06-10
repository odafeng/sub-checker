"""Crossref API client for DOI-based citation verification.

Polite pool rate: ~50 req/sec with mailto in User-Agent.
Retries on 429/5xx with exponential backoff.
"""

from __future__ import annotations

from typing import Any

import httpx

from sub_checker.services.http_client import RateLimitedClient

CROSSREF_WORKS_URL = "https://api.crossref.org/works"

_SELECT_FIELDS = "DOI,title,author,published-print,published-online,container-title,abstract"


def _parse_work(item: dict[str, Any]) -> dict[str, Any]:
    """Convert a Crossref work item into our normalized paper dict."""
    authors = []
    for a in item.get("author", []):
        name = f"{a.get('family', '')} {a.get('given', '')}".strip()
        if name:
            authors.append(name)
    pub_date = item.get("published-print") or item.get("published-online") or {}
    date_parts = pub_date.get("date-parts", [[None]])[0]
    pub_year = date_parts[0] if date_parts else None
    titles = item.get("title", [])
    return {
        "doi": item.get("DOI", ""),
        "title": titles[0] if titles else "",
        "authors": authors,
        "year": pub_year,
        "journal": (item.get("container-title") or [""])[0],
        "abstract": item.get("abstract", ""),
    }


class CrossrefClient(RateLimitedClient):
    service_name = "crossref"

    def __init__(self, max_concurrent: int = 3, mailto: str | None = None):
        # Crossref's polite pool requires a real contact address in the User-Agent
        ua = "sub-checker/0.1"
        if mailto:
            ua += f" (mailto:{mailto})"
        super().__init__(
            min_interval=0.25,
            max_concurrent=max_concurrent,
            headers={"User-Agent": ua},
        )
        self._cache: dict[str, Any] = {}

    async def search(
        self, author: str, title_keywords: str, year: str = "", max_results: int = 3
    ) -> list[dict[str, Any]]:
        """Search Crossref by author + title keywords."""
        query = f"{author} {title_keywords}".strip()
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key] or []

        params: dict[str, str] = {
            "query": query,
            "rows": str(max_results),
            "select": _SELECT_FIELDS,
        }
        if year:
            params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
        try:
            resp = await self._rate_limited_get(CROSSREF_WORKS_URL, params)
        except httpx.HTTPError:
            return []

        items = resp.json().get("message", {}).get("items", [])
        results = [_parse_work(item) for item in items]
        self._cache[cache_key] = results
        return results

    async def get_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Look up a specific paper by DOI."""
        cache_key = f"doi:{doi}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = await self._rate_limited_get(
                f"{CROSSREF_WORKS_URL}/{doi}",
                params={"select": _SELECT_FIELDS},
            )
        except httpx.HTTPError:
            self._cache[cache_key] = None
            return None

        result = _parse_work(resp.json().get("message", {}))
        self._cache[cache_key] = result
        return result
