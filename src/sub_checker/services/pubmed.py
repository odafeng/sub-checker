"""PubMed API client using NCBI E-utilities.

Rate limits: 3 req/sec without API key, 10 req/sec with API key.
This client enforces rate limiting and retries on 429/5xx errors.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import httpx

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"

logger = logging.getLogger("sub_checker.services.pubmed")

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 8.0)  # seconds


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
        # Rate limit: min interval between requests
        self._min_interval = 0.12 if api_key else 0.35  # ~8/sec or ~3/sec
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()

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

    async def _rate_limited_get(self, url: str, params: dict[str, str]) -> httpx.Response:
        """GET with rate limiting and retry on 429/5xx."""
        client = await self._get_client()

        for attempt in range(_MAX_RETRIES):
            # Enforce rate limit
            async with self._rate_lock:
                now = time.monotonic()
                wait = self._min_interval - (now - self._last_request_time)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_request_time = time.monotonic()

            async with self._semaphore:
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code == 429 or resp.status_code >= 500:
                        backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        logger.warning(
                            "PubMed %d on attempt %d, retrying in %.1fs: %s",
                            resp.status_code,
                            attempt + 1,
                            backoff,
                            url,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    resp.raise_for_status()
                    return resp
                except httpx.HTTPError as e:
                    if attempt < _MAX_RETRIES - 1:
                        backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        logger.warning(
                            "PubMed request failed (attempt %d): %s, retrying in %.1fs",
                            attempt + 1,
                            e,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        raise

        # Should not reach here, but satisfy type checker
        raise httpx.HTTPError("Max retries exceeded")  # type: ignore[call-arg]

    async def search(
        self, author: str, year: str, title_keywords: str = "", max_results: int = 5
    ) -> list[dict[str, Any]]:
        """Search PubMed and return list of {pmid, title}."""
        query_parts = [f"{author}[Author]", f"{year}[Date - Publication]"]
        if title_keywords:
            query_parts.append(f"{title_keywords}[Title]")
        query = " AND ".join(query_parts)

        params = {
            **self._base_params(),
            "db": "pubmed",
            "term": query,
            "retmax": str(max_results),
        }
        resp = await self._rate_limited_get(ESEARCH_URL, params)

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

        params = {
            **self._base_params(),
            "db": "pubmed",
            "id": pmid,
            "rettype": "abstract",
            "retmode": "text",
        }
        resp = await self._rate_limited_get(EFETCH_URL, params)

        text = resp.text.strip()
        self._abstract_cache[pmid] = text
        return text

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
