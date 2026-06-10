"""PubMed API client using NCBI E-utilities.

Rate limits: 3 req/sec without API key, 10 req/sec with API key.
This client enforces rate limiting and retries on 429/5xx errors.
"""

from __future__ import annotations

from typing import Any

from sub_checker.services.http_client import RateLimitedClient

ESEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


class PubMedClient(RateLimitedClient):
    service_name = "pubmed"

    def __init__(
        self,
        email: str | None = None,
        api_key: str | None = None,
        max_concurrent: int = 3,
    ):
        super().__init__(
            min_interval=0.12 if api_key else 0.35,  # ~8/sec or ~3/sec
            max_concurrent=max_concurrent,
        )
        self.email = email
        self.api_key = api_key
        self._abstract_cache: dict[str, str] = {}

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

        # Fetch all titles in a single esummary request (avoids one efetch per PMID)
        titles = await self._get_titles(id_list)
        return [{"pmid": pmid, "title": titles.get(pmid, pmid)} for pmid in id_list]

    async def _get_titles(self, pmids: list[str]) -> dict[str, str]:
        """Fetch titles for multiple PMIDs in one esummary call."""
        params = {
            **self._base_params(),
            "db": "pubmed",
            "id": ",".join(pmids),
        }
        resp = await self._rate_limited_get(ESUMMARY_URL, params)
        result = resp.json().get("result", {})
        return {
            pmid: result[pmid].get("title", pmid)
            for pmid in pmids
            if isinstance(result.get(pmid), dict)
        }

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
