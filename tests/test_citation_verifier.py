"""Tests for multi-source citation cross-validation."""

from __future__ import annotations

from sub_checker.services.citation_verifier import _cross_validate, _title_similarity


def test_cross_validate_scans_all_results_for_best_match():
    # The true best match is the SECOND result in the source. A loop that broke
    # on the first >0.55 hit would report the weaker first match instead.
    kw = "robotic single stapling technique colorectal anastomosis"
    ref_parsed = {"author": "smith", "year": "2020", "doi": "", "title_keywords": kw}
    partial = {"title": "robotic single stapling technique", "pmid": "1"}
    exact = {"title": kw, "pmid": "2"}

    # Precondition: the partial alone is strong enough to have tripped the old
    # early-break, so this genuinely exercises the fix.
    assert _title_similarity(kw, partial["title"]) > 0.55

    verified = _cross_validate(ref_parsed, [partial, exact], [], [])
    assert verified.best_match.get("pmid") == "2"
    assert verified.best_match.get("title") == kw
