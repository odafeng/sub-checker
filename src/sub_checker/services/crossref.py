"""Crossref API client for DOI-based citation verification."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

CROSSREF_WORKS_URL = "https://api.crossref.org/works"


class CrossrefClient:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache: dict[str, dict[str, Any] | None] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={
                    "User-Agent": "sub-checker/0.1 (mailto:sub-checker@example.com)",
                },
            )
        return self._client

    async def search(
        self, author: str, title_keywords: str, year: str = "", max_results: int = 3
    ) -> list[dict[str, Any]]:
        """Search Crossref by author + title keywords."""
        query = f"{author} {title_keywords}".strip()
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key] or []  # type: ignore[return-value]

        async with self._semaphore:
            client = await self._get_client()
            params: dict[str, str] = {
                "query": query,
                "rows": str(max_results),
                "select": "DOI,title,author,published-print,published-online,container-title,abstract",
            }
            if year:
                params["filter"] = f"from-pub-date:{year},until-pub-date:{year}"
            try:
                resp = await client.get(CROSSREF_WORKS_URL, params=params)
                resp.raise_for_status()
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

        async with self._semaphore:
            client = await self._get_client()
            try:
                resp = await client.get(
                    f"{CROSSREF_WORKS_URL}/{doi}",
                    params={
                        "select": "DOI,title,author,published-print,published-online,container-title,abstract"
                    },
                )
                resp.raise_for_status()
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
