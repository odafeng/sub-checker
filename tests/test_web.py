"""Tests for the DuckDuckGo HTML result parser."""

from __future__ import annotations

from sub_checker.services.web import WebService


def test_ddg_parsing_missing_snippet_does_not_misalign():
    # Result 1 has NO snippet; result 2 does. Pairing two global findall() lists
    # by index would put result 2's snippet onto result 1. Per-result parsing
    # keeps each snippet with its own link.
    html = (
        '<a class="result__a" href="https://a.example/1">Alpha</a>'
        '<a class="result__a" href="https://b.example/2">Beta</a>'
        '<a class="result__snippet" href="#">beta snippet text</a>'
    )
    results = WebService()._parse_ddg_html(html)

    assert len(results) == 2
    assert results[0]["title"] == "Alpha"
    assert results[0]["snippet"] == ""
    assert results[1]["title"] == "Beta"
    assert "beta snippet" in results[1]["snippet"]
