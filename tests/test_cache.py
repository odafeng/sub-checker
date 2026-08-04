from __future__ import annotations

import httpx

from sub_checker.services.cache import DiskCache
from sub_checker.services.web import WebService


def test_disk_cache_persists_across_instances(tmp_path):
    path = tmp_path / "cache.json"
    first = DiskCache(path)
    first["doi"] = {"value": "10.1/example"}
    first.flush()

    second = DiskCache(path)

    assert second["doi"] == {"value": "10.1/example"}


def test_corrupt_disk_cache_recovers_as_empty(tmp_path):
    path = tmp_path / "cache.json"
    path.write_text("not-json", encoding="utf-8")

    cache = DiskCache(path)

    assert "anything" not in cache


async def test_web_page_cache_is_reused_across_runs(tmp_path):
    url = "https://example.org/authors"
    cache_path = tmp_path / "web.json"
    first = WebService(cache_path=cache_path, now=lambda: 1_000.0)

    class FirstClient:
        async def get(self, request_url):
            assert request_url == url
            return httpx.Response(
                200,
                text="<html><body>Ethics approval is required.</body></html>",
                request=httpx.Request("GET", request_url),
            )

    async def first_client():
        return FirstClient()

    first._get_client = first_client  # type: ignore[method-assign]
    assert "Ethics approval" in await first.fetch_page(url)

    second = WebService(cache_path=cache_path, now=lambda: 1_010.0)

    async def no_network():
        raise AssertionError("fresh persistent cache should avoid the network")

    second._get_client = no_network  # type: ignore[method-assign]
    assert "Ethics approval" in await second.fetch_page(url)


async def test_expired_web_page_cache_is_refetched(tmp_path):
    url = "https://example.org/authors"
    cache_path = tmp_path / "web.json"
    first = WebService(cache_path=cache_path, cache_max_age_days=1, now=lambda: 0.0)

    class Client:
        def __init__(self, text):
            self.text = text

        async def get(self, request_url):
            return httpx.Response(
                200,
                text=f"<html><body>{self.text}</body></html>",
                request=httpx.Request("GET", request_url),
            )

    async def old_client():
        return Client("old")

    first._get_client = old_client  # type: ignore[method-assign]
    assert await first.fetch_page(url) == "old"

    second = WebService(
        cache_path=cache_path,
        cache_max_age_days=1,
        now=lambda: 2 * 86_400.0,
    )

    async def new_client():
        return Client("new")

    second._get_client = new_client  # type: ignore[method-assign]
    assert await second.fetch_page(url) == "new"
