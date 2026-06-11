"""Shared rate-limited HTTP client base for external API services.

Provides a lazily-created httpx.AsyncClient, a minimum-interval rate limiter,
a concurrency semaphore, retry with exponential backoff on 429/5xx, and a
circuit breaker that opens after repeated 429s and half-opens after a cooldown.
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx

_MAX_RETRIES = 3
_RETRY_BACKOFF = (1.0, 3.0, 8.0)  # seconds

# Circuit breaker: after this many consecutive 429s, skip further requests.
_CIRCUIT_BREAKER_THRESHOLD = 5
# After this many seconds, allow a single probe request (half-open).
_CIRCUIT_BREAKER_COOLDOWN = 60.0


class CircuitOpenError(httpx.HTTPError):
    """Raised when the circuit breaker is open and the request is skipped.

    Subclasses httpx.HTTPError so callers that already handle HTTP failures
    degrade gracefully, but stays distinct so the retry loop never swallows it.
    """


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
        self._consecutive_429s = 0
        self._circuit_open = False
        self._circuit_opened_at = 0.0

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout, headers=self._headers)
        return self._client

    def _check_circuit(self) -> None:
        """Raise CircuitOpenError if open; half-open after the cooldown."""
        if not self._circuit_open:
            return
        if time.monotonic() - self._circuit_opened_at >= _CIRCUIT_BREAKER_COOLDOWN:
            # Half-open: allow probes; a single further 429 re-opens immediately.
            self._circuit_open = False
            self._consecutive_429s = _CIRCUIT_BREAKER_THRESHOLD - 1
            self._logger.info(
                "%s circuit breaker half-open after cooldown, allowing probe",
                self.service_name,
            )
            return
        raise CircuitOpenError(f"{self.service_name}: circuit breaker open, skipping request")

    def _record_429(self) -> None:
        """Count a 429; open the circuit at the threshold."""
        self._consecutive_429s += 1
        if self._consecutive_429s >= _CIRCUIT_BREAKER_THRESHOLD:
            self._circuit_open = True
            self._circuit_opened_at = time.monotonic()
            self._logger.warning(
                "%s circuit breaker OPEN after %d consecutive 429s — requests skipped for %.0fs",
                self.service_name,
                self._consecutive_429s,
                _CIRCUIT_BREAKER_COOLDOWN,
            )
            raise CircuitOpenError(f"{self.service_name}: circuit breaker open")

    async def _rate_limited_get(
        self, url: str, params: dict[str, str] | None = None
    ) -> httpx.Response:
        """GET with rate limiting, retry on 429/5xx, and circuit breaker."""
        client = await self._get_client()

        for attempt in range(_MAX_RETRIES):
            self._check_circuit()
            backoff = 0.0

            async with self._semaphore:
                # Rate gate immediately before the actual send, inside the
                # semaphore, so the min-interval spacing matches real send
                # times instead of queue-entry times.
                async with self._rate_lock:
                    now = time.monotonic()
                    wait = self._min_interval - (now - self._last_request_time)
                    if wait > 0:
                        await asyncio.sleep(wait)
                    self._last_request_time = time.monotonic()

                try:
                    resp = await client.get(url, params=params)
                except httpx.HTTPError as e:
                    if attempt >= _MAX_RETRIES - 1:
                        raise
                    backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                    self._logger.warning(
                        "%s request failed (attempt %d): %s, retrying in %.1fs",
                        self.service_name,
                        attempt + 1,
                        e,
                        backoff,
                    )
                else:
                    if resp.status_code == 429 or resp.status_code >= 500:
                        if resp.status_code == 429:
                            self._record_429()  # may raise CircuitOpenError
                        if attempt >= _MAX_RETRIES - 1:
                            raise httpx.HTTPError(
                                f"{self.service_name}: max retries exceeded "
                                f"(last status {resp.status_code})"
                            )
                        backoff = _RETRY_BACKOFF[min(attempt, len(_RETRY_BACKOFF) - 1)]
                        self._logger.warning(
                            "%s %d on attempt %d, retrying in %.1fs: %s",
                            self.service_name,
                            resp.status_code,
                            attempt + 1,
                            backoff,
                            url,
                        )
                    else:
                        resp.raise_for_status()
                        self._consecutive_429s = 0  # reset on success
                        return resp

            # Backoff outside the semaphore so retries don't starve
            # other requests of concurrency slots.
            if backoff > 0:
                await asyncio.sleep(backoff)

        raise httpx.HTTPError(f"{self.service_name}: max retries exceeded")

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
