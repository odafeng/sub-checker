"""Semantic Scholar API client — fallback for papers not found on PubMed."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"
S2_PAPER_URL = "https://api.semanticscholar.org/graph/v1/paper"


class SemanticScholarClient:
    def __init__(self, max_concurrent: int = 3):
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._cache: dict[str, dict[str, Any]] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                headers={"User-Agent": "sub-checker/0.1 (academic manuscript checker)"},
            )
        return self._client

    async def search(
        self, query: str, year: str = "", max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search Semantic Scholar. Returns list of {paperId, title, year, authors, abstract}."""
        cache_key = f"search:{query}:{year}"
        if cache_key in self._cache:
            return self._cache[cache_key].get("results", [])

        async with self._semaphore:
            client = await self._get_client()
            params: dict[str, str] = {
                "query": query,
                "limit": str(max_results),
                "fields": "title,year,authors,abstract,externalIds",
            }
            if year:
                params["year"] = year
            try:
                resp = await client.get(S2_SEARCH_URL, params=params)
                resp.raise_for_status()
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
        """Get paper details by Semantic Scholar paper ID, DOI, or PMID.

        Accepts: S2 paper ID, "DOI:10.xxx", "PMID:12345", "CorpusId:xxx"
        """
        cache_key = f"paper:{paper_id}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        async with self._semaphore:
            client = await self._get_client()
            try:
                resp = await client.get(
                    f"{S2_PAPER_URL}/{paper_id}",
                    params={"fields": "title,year,authors,abstract,externalIds"},
                )
                resp.raise_for_status()
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
