"""Tests for tool functions."""

from sub_checker.models import Manuscript
from sub_checker.tools.filesystem_tools import check_file_exists, list_figures
from sub_checker.tools.manuscript_tools import (
    extract_citation_numbers,
    get_metadata,
    get_reference_list,
    read_paragraph,
    read_section,
    search_text,
    superscript_run_citations,
)


def test_superscript_run_citations_parses_citation_lists():
    assert superscript_run_citations("15,16") == {15, 16}
    assert superscript_run_citations("5-7") == {5, 6, 7}
    assert superscript_run_citations("3") == {3}


def test_superscript_run_citations_rejects_non_citation_runs():
    assert superscript_run_citations("nd") == set()  # "2nd" tail
    assert superscript_run_citations("a") == set()
    assert superscript_run_citations("") == set()
    assert superscript_run_citations("2023") == set()  # year > 999 bound


def test_read_section(sample_manuscript: Manuscript):
    result = read_section(sample_manuscript, "Introduction")
    assert "Disease Y" in result
    assert "Introduction" in result


def test_read_section_not_found(sample_manuscript: Manuscript):
    result = read_section(sample_manuscript, "Nonexistent")
    assert "not found" in result


def test_read_paragraph(sample_manuscript: Manuscript):
    result = read_paragraph(sample_manuscript, 0)
    assert "Paragraph 0" in result


def test_read_paragraph_out_of_range(sample_manuscript: Manuscript):
    result = read_paragraph(sample_manuscript, 9999)
    assert "out of range" in result


def test_get_reference_list(sample_manuscript: Manuscript):
    result = get_reference_list(sample_manuscript)
    assert "Smith" in result


def test_search_text(sample_manuscript: Manuscript):
    result = search_text(sample_manuscript, "Treatment X")
    assert "match" in result.lower()


def test_search_text_no_match(sample_manuscript: Manuscript):
    result = search_text(sample_manuscript, "xyznonexistent")
    assert "No matches" in result


def test_get_metadata(sample_manuscript: Manuscript):
    result = get_metadata(sample_manuscript)
    assert "word count" in result.lower()
    assert "Title:" in result


def test_list_figures(sample_manuscript: Manuscript):
    result = list_figures(sample_manuscript)
    assert "Figure1.png" in result
    assert "Figure2.png" in result


def test_check_file_exists(sample_manuscript: Manuscript):
    result = check_file_exists(sample_manuscript, "Figure1.png")
    assert "exists" in result.lower()


def test_check_file_not_exists(sample_manuscript: Manuscript):
    result = check_file_exists(sample_manuscript, "Figure99.png")
    assert "NOT exist" in result


def test_extract_citation_numbers_basic():
    text = "First claim [1]. Second claim (2,3). Range [4-6] and en-dash (7–8)."  # noqa: RUF001
    assert extract_citation_numbers(text) == {1, 2, 3, 4, 5, 6, 7, 8}


def test_extract_citation_numbers_ignores_years():
    text = "A study (2023) found X [1]. Earlier work (2010-2015) agrees [2,3]."
    assert extract_citation_numbers(text) == {1, 2, 3}


def test_extract_citation_numbers_ignores_large_page_ranges():
    text = "See pages (1023-1045) for details; the claim itself is from [12]."
    assert extract_citation_numbers(text) == {12}


def test_extract_citation_numbers_ignores_zero():
    text = "No events occurred (0) in the control group [3]."
    assert extract_citation_numbers(text) == {3}
