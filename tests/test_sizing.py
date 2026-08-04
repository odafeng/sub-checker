from sub_checker.models import Manuscript, Paragraph, Section
from sub_checker.sizing import (
    TRUNCATION_MARKER,
    bounded_tool_text,
    chunk_text,
    fit_text,
)
from sub_checker.tools.manuscript_tools import read_section


def test_fit_text_prefers_newline_boundary():
    text, truncated = fit_text("a" * 40 + "\n" + "b" * 40, 50)

    assert truncated is True
    assert text == "a" * 40


def test_fit_text_does_not_cut_to_a_tiny_header():
    text, truncated = fit_text("## Methods\n\n" + "x" * 100, 50)

    assert truncated is True
    assert len(text) == 50
    assert text.endswith("x" * 38)


def test_chunk_text_preserves_every_character():
    text = "a" * 50 + "\n" + "b" * 100

    chunks = chunk_text(text, 60)

    assert all(len(chunk) <= 60 for chunk in chunks)
    assert "".join(chunks) == text.replace("\n", "")


def test_bounded_tool_text_marks_partial_coverage():
    result = bounded_tool_text("x" * 100, label="section 'Methods'", max_chars=30)

    assert result.startswith("x" * 30)
    assert TRUNCATION_MARKER in result
    assert "30 of 100" in result


def test_read_section_bounds_oversized_content():
    paragraph = Paragraph(text="x" * 50_000, index=0, section="Methods")
    manuscript = Manuscript(
        title="Synthetic",
        sections=[Section(heading="Methods", level=1, paragraphs=[paragraph])],
        paragraphs=[paragraph],
        raw_text=paragraph.text,
    )

    result = read_section(manuscript, "Methods")

    assert TRUNCATION_MARKER in result
    assert "first 40000 of 50012" in result
