"""Shared rate-limited HTTP client base for external API services.

Provides a lazily-created httpx.AsyncClient, a minimum-interval rate limiter,
a concurrency semaphore, and retry with exponential backoff on 429/5xx.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 8.0)  # seconds


class RateLimitedClient:
    """Base class: GET with rate limiting, concurrency cap, and retries."""

    service_name: str = "service"

    def __init__(
        self,
        min_interval: float,
        max_concurrent: int = 3,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
    ):
        self._min_interval = min_interval
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._headers = headers or {}
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._last_request_time = 0.0
        self._rate_lock = asyncio.Lock()
        self._logger = logging.getLogger(f"sub_checker.services.{self.service_name}")

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers)
        return self._client

    async def _rate_limited_get(
        self, url: str, params: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET with rate limiting and retry on 429/5xx."""
        client = await self._get_client()

        for attempt in range(_MAX_RETRIES):
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
                        self._logger.warning(
                            "%s %d on attempt %d, retrying in %.1fs: %s",
                            self.service_name,
                            resp.status_code,
                            attempt + 1,
                            backoff,
                            url,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    resp.raise_for_status()
                    return resp
                except httpx.HTTPStatusError:
                    raise
                except httpx.HTTPError as e:
                    if attempt < _MAX_RETRIES - 1:
                        backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        self._logger.warning(
                            "%s request failed (attempt %d): %s, retrying in %.1fs",
                            self.service_name,
                            attempt + 1,
                            e,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                    else:
                        raise

        raise httpx.HTTPError(f"{self.service_name}: max retries exceeded")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
