"""Tests for http_client circuit breaker and citation_verifier parsing logic."""

from __future__ import annotations

import time

import httpx
import pytest

from sub_checker.services import http_client as hc
from sub_checker.services.citation_verifier import (
    _cross_validate,
    _extract_doi,
    _extract_year,
)
from sub_checker.services.http_client import CircuitOpenError, RateLimitedClient


class _Always429Client:
    """Stub httpx client that always returns 429."""

    def __init__(self):
        self.calls = 0

    async def get(self, url, params=None):
        self.calls += 1
        return httpx.Response(429, request=httpx.Request("GET", url))


@pytest.fixture
def fast_client(monkeypatch):
    """RateLimitedClient with zero backoff and a stubbed transport."""
    monkeypatch.setattr(hc, "_RETRY_BACKOFF", (0.0, 0.0, 0.0))
    client = RateLimitedClient(min_interval=0.0)
    stub = _Always429Client()

    async def _get_client():
        return stub

    client._get_client = _get_client  # type: ignore[method-assign]
    return client, stub


@pytest.mark.asyncio
async def test_circuit_breaker_opens_and_skips_requests(fast_client):
    client, stub = fast_client

    # First call: 3 attempts, all 429 → max retries error, counter at 3.
    with pytest.raises(httpx.HTTPError):
        await client._rate_limited_get("https://api.example.com/x")
    assert stub.calls == 3
    assert client._consecutive_429s == 3
    assert not client._circuit_open

    # Second call: attempts 4 and 5 → breaker opens at 5 and raises
    # CircuitOpenError instead of being swallowed by the retry handler.
    with pytest.raises(CircuitOpenError):
        await client._rate_limited_get("https://api.example.com/x")
    assert stub.calls == 5
    assert client._circuit_open

    # Third call: skipped entirely — no real request goes out.
    with pytest.raises(CircuitOpenError):
        await client._rate_limited_get("https://api.example.com/x")
    assert stub.calls == 5


@pytest.mark.asyncio
async def test_circuit_breaker_half_opens_after_cooldown(fast_client):
    client, stub = fast_client
    client._circuit_open = True
    client._consecutive_429s = 5
    client._circuit_opened_at = time.monotonic() - hc._CIRCUIT_BREAKER_COOLDOWN - 1

    # Cooldown elapsed → probe allowed; the probe 429s once and re-opens.
    with pytest.raises(CircuitOpenError):
        await client._rate_limited_get("https://api.example.com/x")
    assert stub.calls == 1  # exactly one probe went out
    assert client._circuit_open


def test_extract_year_ignores_page_ranges():
    assert _extract_year("J Clin Oncol. 2010;28:2013-2019.") == "2010"
    assert _extract_year("Heald RJ (1982) The mesorectum. Br J Surg 69:613-616") == "1982"
    assert _extract_year("No year here") == ""


def test_extract_doi_not_anchored_to_line_end():
    assert _extract_doi("Smith J. Title. J Med. 2020. doi:10.1000/xyz. Accessed 2024.") == (
        "10.1000/xyz"
    )
    assert _extract_doi("https://doi.org/10.1186/s12885-022-09175-2") == (
        "10.1186/s12885-022-09175-2"
    )
    assert _extract_doi("no doi present") == ""


def test_cross_validate_doi_hit_verifies_without_title_keywords():
    parsed = {"author": "Smith", "year": "2020", "doi": "10.1000/xyz", "title_keywords": ""}
    crossref = [{"doi": "10.1000/XYZ", "title": "Some exact paper"}]
    result = _cross_validate(parsed, [], [], crossref)
    assert result.status == "verified"
    assert result.confidence >= 0.9
    assert "crossref" in result.sources_found


def test_cross_validate_no_title_kw_with_results_is_uncertain_not_notfound():
    parsed = {"author": "Smith", "year": "2020", "doi": "", "title_keywords": ""}
    pubmed = [{"pmid": "123", "title": "Could be anything"}]
    result = _cross_validate(parsed, pubmed, [], [])
    assert result.status == "uncertain"


def test_cross_validate_nothing_found():
    parsed = {"author": "Smith", "year": "2020", "doi": "", "title_keywords": "some title"}
    result = _cross_validate(parsed, [], [], [])
    assert result.status == "not_found"
    assert result.confidence == 0.0
