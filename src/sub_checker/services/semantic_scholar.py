"""Semantic Scholar API client — fallback for papers not found on PubMed.

Rate limit: ~100 req/sec for unauthenticated, but practically 1 req/sec is safe.
Retries on 429/5xx with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"

logger = logging.getLogger("sub_checker.services.semantic_scholar")

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 8.0)


class SemanticScholarClient:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache: dict[str, dict[str, Any]] = {}
        self._client: httpx.AsyncClient | None = None
        self._min_interval = 0.35
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "sub-checker/0.1 (academic manuscript checker)"},
            )
        return self._client

    async def _rate_limited_get(
        self, url: str, params: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET with rate limiting and retry."""
        client = await self._get_client()
        for attempt in range(_MAX_RETRIES):
            async with self._rate_lock:
                now = time.monotonic()
                wait = self._min_interval - (now - self._last_request_time)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request_time = time.monotonic()

            async with self._semaphore:
                resp = await client.get(url, params=params)
                if resp.status_code == 429 or resp.status_code >= 500:
                    backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    logger.warning("S2 %d, retry in %.1fs", resp.status_code, backoff)
                    await asyncio.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp

        raise httpx.HTTPError("Max retries exceeded")  # type: ignore[call-arg]

    async def search(
        self, query: str, year: str = "", max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search Semantic Scholar. Returns list of paper dicts."""
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key].get("results", [])

        params: dict[str, str] = {
            "query": query,
            "limit": str(max_results),
            "fields": "title,year,authors,abstract,externalIds",
        }
        if year:
            params["year"] = year
        try:
            resp = await self._rate_limited_get(S2_SEARCH_URL, params)
        except httpx.HTTPError:
            return []

        data = resp.json()
        papers = data.get("data", [])
        results = []
        for p in papers:
            authors = [a.get("name", "") for a in (p.get("authors") or [])]
            ext_ids = p.get("externalIds") or {}
            results.append(
                {
                    "paperId": p.get("paperId", ""),
                    "title": p.get("title", ""),
                    "year": p.get("year"),
                    "authors": authors,
                    "abstract": p.get("abstract") or "",
                    "doi": ext_ids.get("DOI", ""),
                    "pmid": ext_ids.get("PubMed", ""),
                }
            )

        self._cache[cache_key] = {"results": results}
        return results

    async def get_paper(self, paper_id: str) -> dict[str, Any] | None:
        """Get paper details by Semantic Scholar paper ID, DOI, or PMID."""
        cache_key = f"paper:{paper_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = await self._rate_limited_get(
                f"{S2_PAPER_URL}/{paper_id}",
                params={"fields": "title,year,authors,abstract,externalIds"},
            )
        except httpx.HTTPError:
            return None

        data = resp.json()
        authors = [a.get("name", "") for a in (data.get("authors") or [])]
        ext_ids = data.get("externalIds") or {}
        result = {
            "paperId": data.get("paperId", ""),
            "title": data.get("title", ""),
            "year": data.get("year"),
            "authors": authors,
            "abstract": data.get("abstract") or "",
            "doi": ext_ids.get("DOI", ""),
            "pmid": ext_ids.get("PubMed", ""),
        }
        self._cache[cache_key] = result
        return result

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
