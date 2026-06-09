"""Crossref API client for DOI-based citation verification.

Polite pool rate: ~50 req/sec with mailto in User-Agent.
Retries on 429/5xx with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

CROSSREF_WORKS_URL = "https://api.crossref.org/works"

logger = logging.getLogger("sub_checker.services.crossref")

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 8.0)


class CrossrefClient:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache: dict[str, dict[str, Any] | None] = {}
        self._client: httpx.AsyncClient | None = None
        self._min_interval = 0.25
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "sub-checker/0.1 (mailto:sub-checker@example.com)",
                },
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
                    logger.warning("Crossref %d, retry in %.1fs", resp.status_code, backoff)
                    await asyncio.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp

        raise httpx.HTTPError("Max retries exceeded")  # type: ignore[call-arg]

    async def search(
        self, author: str, title_keywords: str, year: str = "", max_results: int = 3
    ) -> list[dict[str, Any]]:
        """Search Crossref by author + title keywords."""
        query = f"{author} {title_keywords}".strip()
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key] or []  # type: ignore[return-value]

        params: dict[str, str] = {
            "query": query,
            "rows": str(max_results),
            "select": "DOI,title,author,published-print,published-online,container-title,abstract",
        }
        if year:
            params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
        try:
            resp = await self._rate_limited_get(CROSSREF_WORKS_URL, params)
        except httpx.HTTPError:
            return []

        data = resp.json()
        items = data.get("message", {}).get("items", [])
        results = []
        for item in items:
            authors = []
            for a in item.get("author", []):
                name = f"{a.get('family', '')} {a.get('given', '')}".strip()
                if name:
                    authors.append(name)
            pub_date = item.get("published-print") or item.get("published-online") or {}
            date_parts = pub_date.get("date-parts", [[None]])[0]
            pub_year = date_parts[0] if date_parts else None
            titles = item.get("title", [])
            results.append(
                {
                    "doi": item.get("DOI", ""),
                    "title": titles[0] if titles else "",
                    "authors": authors,
                    "year": pub_year,
                    "journal": (item.get("container-title") or [""])[0],
                    "abstract": item.get("abstract", ""),
                }
            )

        self._cache[cache_key] = results  # type: ignore[assignment]
        return results

    async def get_by_doi(self, doi: str) -> dict[str, Any] | None:
        """Look up a specific paper by DOI."""
        cache_key = f"doi:{doi}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            resp = await self._rate_limited_get(
                f"{CROSSREF_WORKS_URL}/{doi}",
                params={
                    "select": "DOI,title,author,published-print,published-online,container-title,abstract"
                },
            )
        except httpx.HTTPError:
            self._cache[cache_key] = None
            return None

        item = resp.json().get("message", {})
        authors = []
        for a in item.get("author", []):
            name = f"{a.get('family', '')} {a.get('given', '')}".strip()
            if name:
                authors.append(name)
        pub_date = item.get("published-print") or item.get("published-online") or {}
        date_parts = pub_date.get("date-parts", [[None]])[0]
        pub_year = date_parts[0] if date_parts else None
        titles = item.get("title", [])
        result = {
            "doi": item.get("DOI", ""),
            "title": titles[0] if titles else "",
            "authors": authors,
            "year": pub_year,
            "journal": (item.get("container-title") or [""])[0],
            "abstract": item.get("abstract", ""),
        }
        self._cache[cache_key] = result
        return result

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
