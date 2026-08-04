"""Context-size guards shared by manuscript-reading tools."""

from __future__ import annotations

TRUNCATION_MARKER = "[sub-checker:truncated]"


def fit_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Keep text within a character budget, preferring a newline boundary."""
    if len(text) <= max_chars:
        return text, False
    cut = text.rfind("\n", 0, max_chars)
    # A short heading followed by one very long paragraph must not reduce a
    # 40k budget to just the heading. Prefer a newline only when it preserves
    # at least half of the available context.
    if cut <= max_chars // 2:
        cut = max_chars
    return text[:cut], True


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Split text into complete, size-bounded chunks without losing content."""
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    chunks: list[str] = []
    current = ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
        while len(current) > max_chars:
            chunks.append(current[:max_chars])
            current = current[max_chars:]
    if current.strip():
        chunks.append(current)
    return chunks


def bounded_tool_text(text: str, label: str, max_chars: int) -> str:
    """Return a bounded tool result with an explicit partial-coverage marker."""
    kept, truncated = fit_text(text, max_chars)
    if not truncated:
        return kept
    return (
        f"{kept}\n\n{TRUNCATION_MARKER} {label}: returned the first "
        f"{len(kept)} of {len(text)} characters; remaining content was not checked in this read."
    )
