"""Tests for .docx parser."""

from pathlib import Path

from sub_checker.parsers.docx_parser import parse_docx


def test_parse_docx_sections(sample_docx: Path, sample_figures_dir: Path):
    ms = parse_docx(sample_docx, sample_figures_dir)
    headings = [s.heading for s in ms.sections]
    assert "Abstract" in headings
    assert "Introduction" in headings
    assert "Methods" in headings
    assert "Results" in headings
    assert "Discussion" in headings
    assert "References" in headings


def test_parse_docx_paragraphs(sample_docx: Path, sample_figures_dir: Path):
    ms = parse_docx(sample_docx, sample_figures_dir)
    assert len(ms.paragraphs) > 0
    assert len(ms.raw_text) > 0


def test_parse_docx_references(sample_docx: Path, sample_figures_dir: Path):
    ms = parse_docx(sample_docx, sample_figures_dir)
    assert ms.reference_section is not None
    assert "Smith" in ms.reference_section
    assert "Jones" in ms.reference_section


def test_parse_docx_figure_dir(sample_docx: Path, sample_figures_dir: Path):
    ms = parse_docx(sample_docx, sample_figures_dir)
    assert ms.figure_dir == sample_figures_dir


def test_parse_docx_title(sample_docx: Path, sample_figures_dir: Path):
    ms = parse_docx(sample_docx, sample_figures_dir)
    assert "Treatment X" in ms.title


def test_parse_docx_references_end_at_next_heading(tmp_path: Path):
    """Sections after References (e.g. Figure Legends) must not leak into it."""
    from docx import Document

    doc = Document()
    doc.add_heading("Introduction", level=2)
    doc.add_paragraph("Intro text [1].")
    doc.add_heading("References", level=2)
    doc.add_paragraph("Smith J. (2020). A study. Journal, 1(1), 1-10.")
    doc.add_heading("Figure Legends", level=2)
    doc.add_paragraph("Figure 1. Mechanism of action.")
    path = tmp_path / "ms.docx"
    doc.save(str(path))

    ms = parse_docx(path, None)
    assert ms.reference_section is not None
    assert "Smith" in ms.reference_section
    assert "Mechanism of action" not in ms.reference_section
