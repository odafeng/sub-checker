"""Tests for reference text parsing in the citation verifier."""

from __future__ import annotations

from sub_checker.services.citation_verifier import (
    _extract_first_author,
    _extract_title_keywords,
    _parse_reference,
)


def test_author_vancouver_style():
    assert _extract_first_author("Smith AB, Jones C. A study. Lancet. 2020.") == "Smith"


def test_author_with_numbering_prefix():
    assert _extract_first_author("12. Brunner W, et al. Title here.") == "Brunner"


def test_author_lowercase_particles():
    assert _extract_first_author("van Gijn W, Marijnen CA, et al (2011) Preoperative...") == (
        "van Gijn"
    )
    assert _extract_first_author("de la Portilla F, et al. Outcomes...").startswith("de la")


def test_title_keywords_vancouver_style():
    ref = "Heald RJ, Husband EM. The mesorectum in rectal cancer surgery. Br J Surg. 1982."
    assert _extract_title_keywords(ref) == "The mesorectum in rectal cancer surgery"


def test_title_keywords_springer_year_paren_style():
    ref = "1. Heald RJ, Husband EM, Ryall RD (1982) The mesorectum in rectal cancer surgery"
    kw = _extract_title_keywords(ref)
    assert kw.startswith("The mesorectum")
    assert "Heald" not in kw


def test_parse_reference_combines_fields():
    ref = (
        "3. van Gijn W, Marijnen CA, Nagtegaal ID, et al (2011) Preoperative radiotherapy "
        "combined with total mesorectal excision for resectable rectal cancer"
    )
    parsed = _parse_reference(ref)
    assert parsed["author"] == "van Gijn"
    assert parsed["year"] == "2011"
    assert parsed["title_keywords"].startswith("Preoperative radiotherapy")
