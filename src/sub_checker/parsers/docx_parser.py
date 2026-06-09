"""Parse .docx files into Manuscript model."""

from __future__ import annotations

from pathlib import Path

import docx

from sub_checker.models import Manuscript, Paragraph, Section

_REFERENCE_HEADINGS = {"references", "bibliography", "works cited", "literature cited"}
_ABSTRACT_HEADINGS = {"abstract", "summary"}
# Common section headings that may appear as plain text (Normal style) in .docx
_SECTION_HEADINGS = {
    "introduction",
    "methods",
    "materials and methods",
    "results",
    "discussion",
    "conclusions",
    "conclusion",
    "acknowledgments",
    "acknowledgements",
    "disclosures",
    "funding",
    "figure legends",
    "table legends",
    "supplementary materials",
    "supplementary material",
    "appendix",
}


def parse_docx(docx_path: Path, figure_dir: Path | None = None) -> Manuscript:
    """Parse a .docx file into a Manuscript model."""
    doc = docx.Document(str(docx_path))

    paragraphs: list[Paragraph] = []
    sections: list[Section] = []
    current_section: Section | None = None
    reference_section: str | None = None
    in_references = False
    ref_lines: list[str] = []
    header_lines: list[str] = []  # Text before first heading
    first_heading_seen = False

    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue

        style = para.style
        style_name = ((style.name or "") if style else "").lower()
        is_heading = "heading" in style_name
        is_ref_heading = text.lower() in _REFERENCE_HEADINGS
        is_abstract_heading = text.lower() in _ABSTRACT_HEADINGS
        is_section_heading = text.lower() in _SECTION_HEADINGS

        if is_heading or is_ref_heading or is_abstract_heading or is_section_heading:
            first_heading_seen = True
            level = 1
            for ch in style_name:
                if ch.isdigit():
                    level = int(ch)
                    break

            if is_ref_heading:
                in_references = True

            current_section = Section(heading=text, level=level)
            sections.append(current_section)
            continue

        # Collect text before first heading as header
        if not first_heading_seen:
            header_lines.append(text)

        p = Paragraph(
            text=text,
            index=len(paragraphs),
            section=current_section.heading if current_section else None,
        )
        paragraphs.append(p)

        if current_section:
            current_section.paragraphs.append(p)

        if in_references:
            ref_lines.append(text)

    if ref_lines:
        reference_section = "\n".join(ref_lines)

    raw_text = "\n".join(p.text for p in paragraphs)
    header_text = "\n".join(header_lines)

    # Title: prefer first line before any heading; fall back to first heading
    title = header_lines[0] if header_lines else (sections[0].heading if sections else "Untitled")

    return Manuscript(
        title=title,
        sections=sections,
        paragraphs=paragraphs,
        raw_text=raw_text,
        reference_section=reference_section,
        figure_dir=figure_dir,
        header_text=header_text,
    )
