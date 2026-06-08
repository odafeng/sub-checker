"""PubMed API client using NCBI E-utilities."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedClient:
    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        max_concurrent: int = 3,
    ):
        self.email = email
        self.api_key = api_key
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._abstract_cache: dict[str, str] = {}
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    def _base_params(self) -> dict[str, str]:
        params: dict[str, str] = {"retmode": "json"}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    async def search(
        self, author: str, year: str, title_keywords: str = "", max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search PubMed and return list of {pmid, title}."""
        query_parts = [f"{author}[Author]", f"{year}[Date - Publication]"]
        if title_keywords:
            query_parts.append(f"{title_keywords}[Title]")
        query = " AND ".join(query_parts)

        async with self._semaphore:
            client = await self._get_client()
            params = {
                **self._base_params(),
                "db": "pubmed",
                "term": query,
                "retmax": str(max_results),
            }
            resp = await client.get(ESEARCH_URL, params=params)
            resp.raise_for_status()

        data = resp.json()
        id_list = data.get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []

        # Fetch summaries
        results = []
        for pmid in id_list:
            abstract = await self.get_abstract(pmid)
            title_line = abstract.split("\n")[0] if abstract else pmid
            results.append({"pmid": pmid, "title": title_line})
        return results

    async def get_abstract(self, pmid: str) -> str:
        """Fetch abstract for a given PMID."""
        if pmid in self._abstract_cache:
            return self._abstract_cache[pmid]

        async with self._semaphore:
            client = await self._get_client()
            params = {
                **self._base_params(),
                "db": "pubmed",
                "id": pmid,
                "rettype": "abstract",
                "retmode": "text",
            }
            resp = await client.get(EFETCH_URL, params=params)
            resp.raise_for_status()

        text = resp.text.strip()
        self._abstract_cache[pmid] = text
        return text

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
