"""Tests for tool functions."""

from sub_checker.models import Manuscript
from sub_checker.tools.filesystem_tools import check_file_exists, list_figures
from sub_checker.tools.manuscript_tools import (
    get_metadata,
    get_reference_list,
    read_paragraph,
    read_section,
    search_text,
)


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
