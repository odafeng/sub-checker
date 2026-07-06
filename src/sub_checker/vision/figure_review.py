"""Non-agentic vision check: compare each figure image to its legend."""

from __future__ import annotations

import re

_FIG_LABEL = r"(?:Figure|Fig\.?)\s*"


def extract_figure_legend(raw_text: str, number: int) -> str:
    """Return the legend block for figure `number`, or "".

    Collects the text after each "Figure N" label up to the next figure label
    (any number) or end of text, and returns the longest such block — the real
    legend is typically far longer than an in-text "see Figure N" reference.
    """
    candidates = [
        c.strip()
        for c in re.findall(
            rf"{_FIG_LABEL}{number}\b[.:]?\s*(.*?)(?=\n\s*{_FIG_LABEL}\d|\Z)",
            raw_text,
            re.DOTALL | re.IGNORECASE,
        )
    ]
    return max(candidates, key=len) if candidates else ""
