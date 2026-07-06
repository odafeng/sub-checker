# Superscript citations in the deterministic cross-check

**Date:** 2026-07-07
**Status:** Approved (design)
**Scope:** "A1" — make superscript-number citations visible to the deterministic
citation cross-reference, without touching the faithful text pipeline.

## Problem

`extract_citation_numbers()` only matches bracketed citations (`[15]`, `(15)`,
`[1-3]`). A manuscript that cites with **superscript numbers and no brackets**
(Vancouver/AMA style — e.g. "effect¹⁵,¹⁶") is flattened by the parser to
`effect15,16`, where the digits are indistinguishable from any other number and
carry no brackets. Result: for such manuscripts,

- `citation_exist`'s deterministic pre-scan finds **zero** citation numbers, so
  its cited-vs-reference-list cross-check silently produces nothing; and
- `harness/deterministic.validate_citation_numbers` can't cross-check either.

The information needed to fix this is already in the `.docx`: each run carries
`run.font.superscript` (XML `<w:vertAlign w:val="superscript"/>`). The current
parser drops it because it flattens a paragraph with `para.text`.

Verified: `para.text` yields `"effect15,16"` while the run "15,16" reports
`run.font.superscript is True`.

## Goal (verifiable behavior change)

Superscript-number citations in the manuscript **body** are included in the set
of "cited numbers" used by the deterministic cross-check, so citation-existence
checking works for superscript-style manuscripts — **without** granting them the
power to hard-delete (filter) a finding, because superscript digits are
ambiguous (see below).

Non-goals (explicitly out of scope for A1):
- Changing what any LLM checker *reads* (raw_text stays byte-for-byte faithful).
- Letting `citation_format` reason about superscript vs inline style (that was
  option A2; deferred).
- Detecting superscript inside table cells (rare; different parse path).
- Any vision/screenshot reading (that is the separate "B" track).

## Key decision: the superscript-vs-exponent ambiguity

A superscript number may be a citation ("effect¹⁵") **or** an exponent/unit
("m²", "x³"). No reliable heuristic distinguishes them (both can be a single
digit immediately after a letter). Rather than guess, we lean on the existing
fail-safe design:

> Superscript citation numbers join **`cited`** (so the cross-check sees them)
> but **not `cited_square`** (the exact set that is allowed to hard-*filter*).

Consequences:
- The cross-check works (pre-scan and "is this number cited?" both see them).
- If an exponent like `m²` is mis-read as citation "2", the worst case is that a
  `"reference [2] is never cited"` finding gets **downgraded** (and re-checked by
  the reviewer), never silently deleted. This mirrors the module's existing rule
  that only exact data (bracketed citations) may filter; heuristic signals only
  downgrade. No fragile exponent detector is needed.

## Design

### Representation (R2 — separate channel, faithful text preserved)

`Manuscript` gains one field:

```python
superscript_citations: set[int] = field(default_factory=set)
```

`raw_text` / `body_text` are unchanged and remain faithful — LLM checkers
(incl. `typo_grammar`) never see synthetic brackets.

### Parser (`docx_parser.py`)

For each **body** paragraph (i.e. `not in_references`), iterate `para.runs`.
For a run where `run.font.superscript is True` and `run.text.strip()` matches a
pure citation-list pattern `^\d+(\s*[,\-–]\s*\d+)*$`, extract its numbers using
the same range/comma/`_MAX_CITATION_NUMBER` logic already in
`extract_citation_numbers` (factor that number-parsing into a shared helper so
the two paths cannot diverge). Union the numbers into `superscript_citations`.

Notes:
- Reference-section paragraphs are excluded (matches how `body_text` is built).
- Table cells are not scanned (they go through `_table_row_texts`, a separate
  path). Documented limitation.
- `raw_text` is still produced from `para.text` exactly as today.

### Consumers (union in the superscript set)

- `citation_exist._build_initial_message` pre-scan:
  `cited_nums = extract_citation_numbers(body) | manuscript.superscript_citations`
- `harness/deterministic.validate_citation_numbers`:
  - `cited = extract_citation_numbers(body) | manuscript.superscript_citations`
  - `cited_square = extract_citation_numbers(body, square_only=True)` — **unchanged**
    (superscript deliberately excluded from the filter-capable set).

`extract_citation_numbers()` itself is unchanged (stays a pure text function).

## Testing (success criteria)

1. **Parser:** a body paragraph "effect" + superscript run "15,16" →
   `superscript_citations == {15, 16}`, and `raw_text` contains the faithful
   `effect15,16` (no synthetic brackets).
2. **Pre-scan:** a manuscript whose only citations are superscript numbers →
   `citation_exist` pre-scan `cited_nums` includes them and dangling detection
   works (a superscript "[7]" with 3 references is flagged for verification).
3. **Fail-safe:** superscript citation 15 + an "uncited [15]" claim →
   `validate_citation_numbers` returns **downgrade**, not filter.
4. **Exponent containment:** a body with "m²" + an "uncited [2]" claim →
   downgrade, not filter (ambiguity absorbed, not hard-deleted).
5. Existing bracketed-citation tests remain green (no regression).

## Files touched

| File | Change |
|------|--------|
| `src/sub_checker/models.py` | add `superscript_citations: set[int]` to `Manuscript` |
| `src/sub_checker/tools/manuscript_tools.py` | factor number-parsing into a shared helper reused by the parser |
| `src/sub_checker/parsers/docx_parser.py` | per-run superscript detection on body paragraphs |
| `src/sub_checker/agents/citation_exist.py` | union superscript set into the pre-scan |
| `src/sub_checker/harness/deterministic.py` | union superscript set into `cited` (not `cited_square`) |
| `tests/…` | parser, pre-scan, and deterministic fail-safe tests above |
