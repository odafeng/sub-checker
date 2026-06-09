"""Parse .docx files into Manuscript model."""

from __future__ import annotations

from pathlib import Path

import docx

from sub_checker.models import Manuscript, Paragraph, Section

_REFERENCE_HEADINGS = {"references", "bibliography", "works cited", "literature cited"}


def parse_docx(docx_path: Path, figure_dir: Path | None = None) -> Manuscript:
    """Parse a .docx file into a Manuscript model."""
    doc = docx.Document(str(docx_path))

    paragraphs: list[Paragraph] = []
    sections: list[Section] = []
    current_section: Section | None = None
    reference_section: str | None = None
    in_references = False
    ref_lines: list[str] = []

    for _i, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue

        style = para.style
        style_name = ((style.name or "") if style else "").lower()
        is_heading = "heading" in style_name
        is_ref_heading = text.lower() in _REFERENCE_HEADINGS

        if is_heading or is_ref_heading:
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
    title = sections[0].heading if sections else (paragraphs[0].text if paragraphs else "Untitled")

    return Manuscript(
        title=title,
        sections=sections,
        paragraphs=paragraphs,
        raw_text=raw_text,
        reference_section=reference_section,
        figure_dir=figure_dir,
    )
