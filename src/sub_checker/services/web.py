"""Web search and page fetching service with caching."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from sub_checker.services.cache import DiskCache

_SECONDS_PER_DAY = 86_400


class WebService:
    """Simple web service that fetches pages and extracts text.

    For web search, we use a simple approach: the agent can search
    via a search engine API (configurable) or fall back to direct
    URL fetching for known journal guidelines pages.
    """

    def __init__(
        self,
        cache_path: Path | None = None,
        cache_max_age_days: int = 30,
        now: Callable[[], float] = time.time,
    ) -> None:
        self._page_cache: dict[str, str] = {}
        self._search_cache: dict[str, list[dict[str, Any]]] = {}
        self._client: httpx.AsyncClient | None = None
        self._disk_cache = DiskCache(cache_path) if cache_path else None
        self._cache_max_age_days = cache_max_age_days
        self._now = now

    def _get_persistent(self, bucket: str, key: str) -> Any | None:
        if self._disk_cache is None:
            return None
        records = self._disk_cache.get(bucket, {})
        if not isinstance(records, dict):
            return None
        record = records.get(key)
        if not isinstance(record, dict):
            return None
        stored_at = record.get("stored_at")
        if not isinstance(stored_at, (int, float)):
            return None
        if self._now() - stored_at > self._cache_max_age_days * _SECONDS_PER_DAY:
            return None
        return record.get("value")

    def _put_persistent(self, bucket: str, key: str, value: Any) -> None:
        if self._disk_cache is None:
            return
        records = self._disk_cache.get(bucket, {})
        if not isinstance(records, dict):
            records = {}
        records[key] = {"stored_at": self._now(), "value": value}
        self._disk_cache[bucket] = records
        self._disk_cache.flush()

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
                headers={"User-Agent": "sub-checker/0.1 (academic manuscript checker)"},
            )
        return self._client

    async def search(self, query: str) -> list[dict[str, Any]]:
        """Search the web. Returns list of {title, url, snippet}.

        Currently uses a simple DuckDuckGo HTML scrape approach.
        Can be replaced with Brave Search API or Google Custom Search.
        """
        if query in self._search_cache:
            return self._search_cache[query]
        cached = self._get_persistent("search", query)
        if isinstance(cached, list):
            self._search_cache[query] = cached
            return cached

        client = await self._get_client()
        try:
            resp = await client.get(
                "https://html.duckduckgo.com/html/",
                params={"q": query},
            )
            resp.raise_for_status()
            results = self._parse_ddg_html(resp.text)
        except httpx.HTTPError:
            results = []

        self._search_cache[query] = results
        if results:
            self._put_persistent("search", query, results)
        return results

    def _parse_ddg_html(self, html: str) -> list[dict[str, Any]]:
        """Parse DuckDuckGo HTML results (basic extraction)."""
        results: list[dict[str, Any]] = []
        link_pattern = re.compile(
            r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
            re.DOTALL,
        )
        snippet_pattern = re.compile(
            r'class="result__snippet"[^>]*>(.*?)</(?:a|span|td)',
            re.DOTALL,
        )

        # Parse per-result: split at each result link so a result that lacks a
        # snippet block can't shift every following snippet onto the wrong link
        # (which index-pairing two independent findall() lists would do).
        for segment in re.split(r'(?=class="result__a")', html)[1:]:
            link_match = link_pattern.search(segment)
            if not link_match:
                continue
            url, title = link_match.group(1), link_match.group(2)
            clean_title = re.sub(r"<[^>]+>", "", title).strip()
            snippet_match = snippet_pattern.search(segment)
            snippet = (
                re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip() if snippet_match else ""
            )
            if url.startswith("//duckduckgo.com/l/"):
                # Extract actual URL from DDG redirect
                url_match = re.search(r"uddg=([^&]+)", url)
                if url_match:
                    from urllib.parse import unquote

                    url = unquote(url_match.group(1))
            results.append({"title": clean_title, "url": url, "snippet": snippet})
            if len(results) >= 10:
                break

        return results

    async def fetch_page(self, url: str) -> str:
        """Fetch a URL and extract text content."""
        if url in self._page_cache:
            return self._page_cache[url]
        cached = self._get_persistent("pages", url)
        if isinstance(cached, str):
            self._page_cache[url] = cached
            return cached

        client = await self._get_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            text = self._extract_text(resp.text)
        except httpx.HTTPError as e:
            # Do NOT cache failures — a transient timeout would otherwise
            # poison this URL for the rest of the run.
            return f"Error fetching {url}: {e}"

        self._page_cache[url] = text
        self._put_persistent("pages", url, text)
        return text

    def _extract_text(self, html: str) -> str:
        """Extract readable text from HTML (simple approach)."""
        # Remove script and style tags
        text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL)
        # Remove HTML tags
        text = re.sub(r"<[^>]+>", " ", text)
        # Clean up whitespace
        text = re.sub(r"\s+", " ", text).strip()
        # Decode HTML entities
        import html as html_module

        text = html_module.unescape(text)
        return text

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
