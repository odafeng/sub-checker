"""Tools for agents to read manuscript content."""

from __future__ import annotations

import re

from sub_checker.models import Manuscript

# Numbers ABOVE this are not plausible citation numbers \u2014 they are
# years like (2023), page ranges like (1023-1045), or sample sizes.
# (The boundary value itself is inclusive: [999] counts as a citation.)
_MAX_CITATION_NUMBER = 999


def extract_citation_numbers(raw_text: str, square_only: bool = False) -> set[int]:
    """Deterministic extraction of all numbered citations from manuscript text.

    Handles: (1), [1], (1-3), [1-3], (1,2,5), (1, 2, 5), etc.
    Year-like numbers such as (2023) and ranges with implausibly large
    endpoints are excluded.
    Returns the set of all individual reference numbers found.

    When ``square_only`` is True, only square-bracket forms ([1], [1-3]) are
    matched. Round-paren forms like "(1)" are ambiguous \u2014 they are equally
    likely to be inline enumerations ("aims: (1) safety, (2) efficacy") or
    parenthetical data \u2014 so a caller that must not act on that ambiguity can
    restrict extraction to the unambiguous bracket citation syntax.
    """
    cited: set[int] = set()
    # Match patterns like (1), [1], (1-3), [1,2,5], (1, 2, 5-7), etc.
    pattern = r"\[([\d,\-\u2013\s]+)\]" if square_only else r"[\(\[]([\d,\-\u2013\s]+)[\)\]]"
    for m in re.findall(pattern, raw_text):
        cited |= _numbers_in_citation_group(m)
    return cited


# A superscript run is treated as a citation list only if it is nothing but
# digits, commas, and hyphen/en-dash ranges \u2014 "15", "1,2", "5-7". This still
# matches a bare "2" (which could be an exponent like m\u00b2); callers must keep
# superscript numbers out of the filter-capable set so that ambiguity can only
# downgrade, never hard-delete (see the design's fail-safe).
_SUPERSCRIPT_CITATION_RE = re.compile(r"^\d+(?:\s*[,\-\u2013]\s*\d+)*$")


def _numbers_in_citation_group(group: str) -> set[int]:
    """Parse a citation group body like '1, 2, 5-7' into individual numbers.

    Years and implausibly large values are excluded via _MAX_CITATION_NUMBER;
    malformed or out-of-range ranges are dropped.
    """
    found: set[int] = set()
    # Match a range ("5-7", "5 \u2013 7" with spaces) or a lone number, left to
    # right. Matching the whole range as one token means spaces around the dash
    # no longer split it into disconnected endpoints (which dropped the middle).
    for m in re.finditer(r"(\d+)\s*[\u2013-]\s*(\d+)|(\d+)", group):
        if m.group(1) is not None:
            lo, hi = int(m.group(1)), int(m.group(2))
            if 1 <= lo <= hi <= _MAX_CITATION_NUMBER:
                found.update(range(lo, hi + 1))
        else:
            n = int(m.group(3))
            if 1 <= n <= _MAX_CITATION_NUMBER:  # citations are 1-based; (0) is data
                found.add(n)
    return found


def superscript_run_citations(run_text: str) -> set[int]:
    """Numbers from a superscript run's text, if it is a pure citation list.

    Returns an empty set for runs that aren't citation-shaped (e.g. the 'nd' in
    a superscript '2nd', stray letters). A bare '2' still parses to {2}.
    """
    text = run_text.strip()
    if not text or not _SUPERSCRIPT_CITATION_RE.match(text):
        return set()
    return _numbers_in_citation_group(text)


_REF_ENTRY_START = re.compile(r"^\d{1,3}[.)\s]")


def reference_entries(reference_section: str | None) -> list[str]:
    """Reconstruct reference entries from the reference section.

    A numbered list ("1. ...", "2) ...") is split on the numbered lines, so
    wrapped continuation lines and stray non-reference content (table
    captions/notes that the parser couldn't fully separate) don't inflate the
    count. If no line is numbered (Word auto-numbering stripped during
    extraction), every non-empty line is treated as an entry.
    """
    if not reference_section:
        return []
    lines = [line.strip() for line in reference_section.split("\n") if line.strip()]
    numbered = [line for line in lines if _REF_ENTRY_START.match(line)]
    return numbered if numbered else lines


def count_references(reference_section: str | None) -> int:
    """Count reference entries in the reference list."""
    return len(reference_entries(reference_section))


def read_section(manuscript: Manuscript, section_name: str) -> str:
    """Read a section by name (case-insensitive partial match)."""
    section_name_lower = section_name.lower()
    for section in manuscript.sections:
        if section_name_lower in section.heading.lower():
            if not section.paragraphs:
                return f"Section '{section.heading}' has no paragraphs."
            text = "\n\n".join(p.text for p in section.paragraphs)
            return f"## {section.heading}\n\n{text}"
    available = [s.heading for s in manuscript.sections]
    return f"Section '{section_name}' not found. Available sections: {available}"


def read_paragraph(manuscript: Manuscript, index: int) -> str:
    """Read a specific paragraph by index."""
    if 0 <= index < len(manuscript.paragraphs):
        p = manuscript.paragraphs[index]
        section_info = f" (Section: {p.section})" if p.section else ""
        return f"Paragraph {index}{section_info}:\n{p.text}"
    return f"Paragraph index {index} out of range (0-{len(manuscript.paragraphs) - 1})."


def read_manuscript_header(manuscript: Manuscript) -> str:
    """Return raw text before the first heading (title, authors, abstract, etc.)."""
    if manuscript.header_text:
        return (
            "--- Raw document header (text before first heading) ---\n"
            f"{manuscript.header_text}\n"
            "--- End of header ---\n"
            "NOTE: This is the raw text at the start of the .docx file, before any "
            "heading-styled paragraph. It typically contains the title, author list, "
            "affiliations, and sometimes the abstract. Use this to determine the "
            "manuscript title and author information."
        )
    return "No text found before the first heading in the document."


def get_reference_list(manuscript: Manuscript) -> str:
    """Get the reference list section."""
    if manuscript.reference_section:
        return (
            f"{manuscript.reference_section}\n\n"
            "NOTE: Reference list numbering may be missing above if the original "
            ".docx uses Word auto-numbered lists — the numbers are stored as list "
            "formatting metadata and are stripped during text extraction. Do NOT "
            "report missing numbering as an error. Assume references are numbered "
            "sequentially (1, 2, 3, ...) in the order they appear."
        )
    return "No reference section found in the manuscript."


def search_text(manuscript: Manuscript, query: str) -> str:
    """Search for text in the manuscript, return matching paragraphs."""
    query_lower = query.lower()
    matches = []
    for p in manuscript.paragraphs:
        if query_lower in p.text.lower():
            section_info = f" (Section: {p.section})" if p.section else ""
            matches.append(f"Paragraph {p.index}{section_info}: {p.text[:200]}...")
    if not matches:
        return f"No matches found for '{query}'."
    return f"Found {len(matches)} match(es):\n\n" + "\n\n".join(matches[:20])


def get_metadata(manuscript: Manuscript) -> str:
    """Get manuscript metadata: word count, sections, etc."""
    words = manuscript.raw_text.split()
    section_list = [s.heading for s in manuscript.sections]

    # Count figures/tables mentioned
    fig_refs = set(re.findall(r"(?:Figure|Fig\.?)\s*(\d+)", manuscript.raw_text, re.IGNORECASE))
    table_refs = set(re.findall(r"Table\s*(\d+)", manuscript.raw_text, re.IGNORECASE))

    # Abstract word count
    abstract_words = 0
    for s in manuscript.sections:
        if "abstract" in s.heading.lower():
            abstract_words = sum(len(p.text.split()) for p in s.paragraphs)
            break

    # Check for keywords section
    has_keywords = any("keyword" in s.heading.lower() for s in manuscript.sections)

    return (
        f"Title: {manuscript.title}\n"
        f"Title word count: {len(manuscript.title.split())}\n"
        f"Total word count: {len(words)}\n"
        f"Abstract word count: {abstract_words}\n"
        f"Sections: {section_list}\n"
        f"Section count: {len(section_list)}\n"
        f"Paragraph count: {len(manuscript.paragraphs)}\n"
        f"Figures referenced: {sorted(fig_refs)}\n"
        f"Tables referenced: {sorted(table_refs)}\n"
        f"Has keywords section: {has_keywords}\n"
        f"Has reference section: {manuscript.reference_section is not None}\n"
        f"Figure directory: {manuscript.figure_dir}"
    )


# Tool definitions for Claude API
TOOL_READ_SECTION = {
    "name": "read_section",
    "description": "Read a section of the manuscript by name (case-insensitive partial match).",
    "input_schema": {
        "type": "object",
        "properties": {
            "section_name": {
                "type": "string",
                "description": "Name of the section to read (e.g. 'Methods', 'Results')",
            }
        },
        "required": ["section_name"],
    },
}

TOOL_READ_PARAGRAPH = {
    "name": "read_paragraph",
    "description": "Read a specific paragraph by its index number.",
    "input_schema": {
        "type": "object",
        "properties": {
            "index": {
                "type": "integer",
                "description": "Paragraph index (0-based)",
            }
        },
        "required": ["index"],
    },
}

TOOL_READ_MANUSCRIPT_HEADER = {
    "name": "read_manuscript_header",
    "description": (
        "Read the raw text at the start of the document, before the first heading. "
        "This typically contains the manuscript title, author list, affiliations, "
        "correspondence info, and sometimes the abstract. Use this to determine the "
        "true title and author information regardless of Word styling."
    ),
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

TOOL_GET_REFERENCE_LIST = {
    "name": "get_reference_list",
    "description": "Get the full reference list / bibliography section of the manuscript.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}

TOOL_SEARCH_TEXT = {
    "name": "search_text",
    "description": "Search for a keyword or phrase in the manuscript. Returns matching paragraphs.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Text to search for (case-insensitive)",
            }
        },
        "required": ["query"],
    },
}

TOOL_GET_METADATA = {
    "name": "get_metadata",
    "description": "Get manuscript metadata: word count, section list, title length, abstract word count, figure/table counts, etc.",
    "input_schema": {
        "type": "object",
        "properties": {},
    },
}
