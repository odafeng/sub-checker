# Superscript Citations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make superscript-number citations (e.g. "effect¹⁵,¹⁶") visible to the deterministic citation cross-check, without touching the faithful text pipeline or granting them hard-filter power.

**Architecture:** The parser reads runs per-run, detects `run.font.superscript`, and collects citation-pattern superscript numbers from **body** paragraphs into a new `Manuscript.superscript_citations` set. The two consumers of "cited numbers" (the `citation_exist` pre-scan and `harness/deterministic`) union this set into `cited` — but NOT into the filter-capable `cited_square` — so the cross-check works while the superscript-vs-exponent ambiguity is absorbed by the existing fail-safe (downgrade, never hard-filter).

**Tech Stack:** Python 3.11+, python-docx, pytest (asyncio auto).

## Global Constraints

- Python floor: 3.11 (`from __future__ import annotations` already used).
- Lint/format: ruff (E,W,F,I,N,UP,B,SIM,RUF; E501 ignored); `ruff format`.
- Types: pyright basic, 0 errors.
- `raw_text` / `body_text` MUST remain byte-for-byte faithful (no synthetic brackets).
- Superscript numbers join `cited` but NEVER `cited_square`.
- `_MAX_CITATION_NUMBER = 999` bound and range/comma parsing reused, not duplicated.

---

### Task 1: Shared citation-number parser + superscript-run helper

**Files:**
- Modify: `src/sub_checker/tools/manuscript_tools.py` (refactor `extract_citation_numbers`, add two helpers)
- Test: `tests/test_tools.py`

**Interfaces:**
- Produces:
  - `_numbers_in_citation_group(group: str) -> set[int]` — parses a group body like `"1, 2, 5-7"` into numbers (range expansion, `_MAX_CITATION_NUMBER` bound).
  - `superscript_run_citations(run_text: str) -> set[int]` — numbers from a superscript run's text IF it matches a pure citation-list pattern; else empty set.
  - `extract_citation_numbers(raw_text, square_only=False)` — unchanged behavior, now delegates to `_numbers_in_citation_group`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_tools.py`:

```python
from sub_checker.tools.manuscript_tools import superscript_run_citations


def test_superscript_run_citations_parses_citation_lists():
    assert superscript_run_citations("15,16") == {15, 16}
    assert superscript_run_citations("5-7") == {5, 6, 7}
    assert superscript_run_citations("3") == {3}


def test_superscript_run_citations_rejects_non_citation_runs():
    assert superscript_run_citations("nd") == set()      # "2nd" tail
    assert superscript_run_citations("a") == set()
    assert superscript_run_citations("") == set()
    assert superscript_run_citations("2023") == set()     # year > 999 bound
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_tools.py -k superscript -v`
Expected: FAIL with `ImportError: cannot import name 'superscript_run_citations'`

- [ ] **Step 3: Write minimal implementation**

In `src/sub_checker/tools/manuscript_tools.py`, replace the body of `extract_citation_numbers` and add the helpers. The current inner loop:

```python
    cited: set[int] = set()
    pattern = r"\[([\d,\-–\s]+)\]" if square_only else r"[\(\[]([\d,\-–\s]+)[\)\]]"
    for m in re.findall(pattern, raw_text):
        for part in re.split(r"[,\s]+", m):
            part = part.strip()
            if "–" in part or "-" in part:  # en dash or hyphen
                rng = re.split(r"[–-]", part)
                if len(rng) == 2 and rng[0].strip().isdigit() and rng[1].strip().isdigit():
                    lo, hi = int(rng[0].strip()), int(rng[1].strip())
                    if 1 <= lo <= hi <= _MAX_CITATION_NUMBER:
                        cited.update(range(lo, hi + 1))
            elif part.isdigit():
                n = int(part)
                if 1 <= n <= _MAX_CITATION_NUMBER:  # citations are 1-based; (0) is data
                    cited.add(n)
    return cited
```

becomes:

```python
    cited: set[int] = set()
    pattern = r"\[([\d,\-–\s]+)\]" if square_only else r"[\(\[]([\d,\-–\s]+)[\)\]]"
    for m in re.findall(pattern, raw_text):
        cited |= _numbers_in_citation_group(m)
    return cited
```

Add above `extract_citation_numbers` (after `_MAX_CITATION_NUMBER`):

```python
# A superscript run is treated as a citation list only if it is nothing but
# digits, commas, and hyphen/en-dash ranges — "15", "1,2", "5-7". This still
# matches a bare "2" (which could be an exponent like m²); callers must keep
# superscript numbers out of the filter-capable set so that ambiguity can only
# downgrade, never hard-delete (see the design's fail-safe).
_SUPERSCRIPT_CITATION_RE = re.compile(r"^\d+(?:\s*[,\-–]\s*\d+)*$")


def _numbers_in_citation_group(group: str) -> set[int]:
    """Parse a citation group body like '1, 2, 5-7' into individual numbers.

    Years and implausibly large values are excluded via _MAX_CITATION_NUMBER;
    malformed or out-of-range ranges are dropped.
    """
    found: set[int] = set()
    for part in re.split(r"[,\s]+", group):
        part = part.strip()
        if not part:
            continue
        if "–" in part or "-" in part:  # en dash or hyphen
            rng = re.split(r"[–-]", part)
            if len(rng) == 2 and rng[0].strip().isdigit() and rng[1].strip().isdigit():
                lo, hi = int(rng[0].strip()), int(rng[1].strip())
                if 1 <= lo <= hi <= _MAX_CITATION_NUMBER:
                    found.update(range(lo, hi + 1))
        elif part.isdigit():
            n = int(part)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_tools.py -v`
Expected: PASS (new superscript tests + existing extract_citation_numbers tests unchanged)

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/tools/manuscript_tools.py tests/test_tools.py
git commit -m "refactor: extract shared citation-number parser + superscript-run helper"
```

---

### Task 2: `superscript_citations` field + parser population

**Files:**
- Modify: `src/sub_checker/models.py` (add field to `Manuscript`)
- Modify: `src/sub_checker/parsers/docx_parser.py` (accumulate + pass through)
- Test: `tests/test_docx_parser.py`

**Interfaces:**
- Consumes: `superscript_run_citations` (Task 1).
- Produces: `Manuscript.superscript_citations: set[int]` populated from body paragraphs.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_docx_parser.py` (it already imports `docx` and `parse_docx`, `Path`):

```python
def test_superscript_citations_collected_from_body(tmp_path: Path):
    import docx

    doc = docx.Document()
    doc.add_heading("Introduction", level=1)
    p = doc.add_paragraph()
    p.add_run("The effect was robust")
    sup = p.add_run("15,16")
    sup.font.superscript = True
    p.add_run(" across cohorts.")
    path = tmp_path / "sup.docx"
    doc.save(str(path))

    ms = parse_docx(path, None)
    assert ms.superscript_citations == {15, 16}
    # raw_text stays faithful — no synthetic brackets
    assert "robust15,16" in ms.raw_text
    assert "[15,16]" not in ms.raw_text


def test_superscript_affiliation_markers_not_collected(tmp_path: Path):
    # Superscript numbers in the header (author affiliation markers) must NOT
    # be treated as citations.
    import docx

    doc = docx.Document()
    hp = doc.add_paragraph()
    hp.add_run("Jane Doe")
    aff = hp.add_run("1,2")
    aff.font.superscript = True
    doc.add_heading("Introduction", level=1)
    doc.add_paragraph("Body text with no citations here.")
    path = tmp_path / "aff.docx"
    doc.save(str(path))

    ms = parse_docx(path, None)
    assert ms.superscript_citations == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_docx_parser.py -k superscript -v`
Expected: FAIL with `AttributeError: 'Manuscript' object has no attribute 'superscript_citations'`

- [ ] **Step 3a: Add the model field**

In `src/sub_checker/models.py`, add to the `Manuscript` dataclass (after `body_text`):

```python
    superscript_citations: set[int] = field(default_factory=set)  # numbers cited via superscript (body only)
```

(`field` is already imported in models.py.)

- [ ] **Step 3b: Populate it in the parser**

In `src/sub_checker/parsers/docx_parser.py`:

Add the import near the top (with the other `manuscript_tools`-adjacent imports is fine, but the parser currently imports only from `docx` and `models`; add a new import line):

```python
from sub_checker.tools.manuscript_tools import superscript_run_citations
```

Add an accumulator beside the others (`header_lines: list[str] = []` block):

```python
    superscript_citations: set[int] = set()
```

In the content-paragraph path, immediately BEFORE the existing `add_content_paragraph(text)` call at the end of the loop, insert:

```python
        # Collect superscript-number citations from the body only. Excludes the
        # reference list and the pre-heading header (author affiliation markers
        # are superscript numbers too, but they are not citations).
        if first_heading_seen and not in_references:
            for run in para.runs:
                if run.font.superscript:
                    superscript_citations |= superscript_run_citations(run.text)
```

In the final `return Manuscript(...)`, add the field:

```python
        superscript_citations=superscript_citations,
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_docx_parser.py -v`
Expected: PASS (both new tests + existing parser tests)

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/models.py src/sub_checker/parsers/docx_parser.py tests/test_docx_parser.py
git commit -m "feat: parse superscript citation numbers from docx body"
```

---

### Task 3: Feed superscript citations into the `citation_exist` pre-scan

**Files:**
- Modify: `src/sub_checker/agents/citation_exist.py:45` (the `cited_nums` line)
- Test: `tests/test_agents/test_citation_exist.py`

**Interfaces:**
- Consumes: `Manuscript.superscript_citations` (Task 2).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_agents/test_citation_exist.py` (it already has the `_ms` helper and imports `CitationExistAgent`, `Config`, `Manuscript`):

```python
def test_prescan_includes_superscript_citations():
    # Body text has no bracketed citations, only a superscript "[7]"-equivalent.
    ms = _ms("Effect was large.", reference_section="1. A.\n2. B.\n3. C.")
    ms.superscript_citations = {7}
    msg = CitationExistAgent()._build_initial_message(ms, Config(cot_dir="disabled"))
    # 7 is cited (via superscript) but only 3 references exist → dangling
    assert "NOT in the reference list" in msg
    assert "[7]" in msg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agents/test_citation_exist.py -k superscript -v`
Expected: FAIL (7 not in `cited_nums`, so no dangling line)

- [ ] **Step 3: Write minimal implementation**

In `src/sub_checker/agents/citation_exist.py`, change the `cited_nums` line (currently line 45):

```python
        cited_nums = extract_citation_numbers(manuscript.body_text or manuscript.raw_text)
```

to:

```python
        cited_nums = (
            extract_citation_numbers(manuscript.body_text or manuscript.raw_text)
            | manuscript.superscript_citations
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_agents/test_citation_exist.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/agents/citation_exist.py tests/test_agents/test_citation_exist.py
git commit -m "feat: include superscript citations in citation_exist pre-scan"
```

---

### Task 4: Feed superscript citations into the deterministic cross-check (fail-safe)

**Files:**
- Modify: `src/sub_checker/harness/deterministic.py` (the `cited` computation in `validate_citation_numbers`)
- Test: `tests/test_harness.py`

**Interfaces:**
- Consumes: `Manuscript.superscript_citations` (Task 2).
- Constraint: union into `cited` only; `cited_square` stays bracket-only.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_harness.py` (it has `_finding`, `_manuscript`, and imports `validate_citation_numbers`). `_manuscript` currently accepts `raw_text` and `reference_section`; superscript is set on the returned object:

```python
def test_uncited_superscript_citation_downgraded_not_filtered():
    # A superscript citation [15] contradicts an "uncited [15]" claim, but
    # superscript is NOT in the filter-capable set → downgrade, never filter.
    ms = _manuscript(raw_text="No bracketed citations here.")
    ms.superscript_citations = {15}
    f = _finding(message="Reference 15 is never cited", claim_type="uncited_reference", ref_number=15)
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"


def test_superscript_exponent_cannot_hard_filter():
    # Even if an exponent like m² is mis-read as superscript "2", an
    # "uncited [2]" finding is only downgraded, never deleted.
    ms = _manuscript(raw_text="Area was 4 m2 in size.")
    ms.superscript_citations = {2}  # as the parser would yield for m²
    f = _finding(message="Reference 2 is never cited", claim_type="uncited_reference", ref_number=2)
    actions = validate_citation_numbers([f], ms)
    assert len(actions) == 1
    assert actions[0][1] == "downgrade"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_harness.py -k superscript -v`
Expected: FAIL (superscript not in `cited`, so no action is produced → `len(actions) == 0`)

- [ ] **Step 3: Write minimal implementation**

In `src/sub_checker/harness/deterministic.py`, in `validate_citation_numbers`, change:

```python
    body = manuscript.body_text or manuscript.raw_text
    cited = extract_citation_numbers(body)
```

to:

```python
    body = manuscript.body_text or manuscript.raw_text
    # Superscript citations join `cited` (so the cross-check sees them) but are
    # deliberately kept out of `cited_square` below: a superscript number could
    # be an exponent (m²), so it may only downgrade, never hard-filter.
    cited = extract_citation_numbers(body) | manuscript.superscript_citations
```

Leave the `cited_square = extract_citation_numbers(body, square_only=True)` line unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_harness.py -v`
Expected: PASS

- [ ] **Step 5: Full gate + commit**

```bash
python -m pytest -q
python -m ruff check . && python -m ruff format --check . && python -m pyright
git add src/sub_checker/harness/deterministic.py tests/test_harness.py
git commit -m "feat: include superscript citations in deterministic cross-check (downgrade-only)"
```

Expected: all tests pass, ruff/format/pyright clean.

---

## Self-Review

**Spec coverage:**
- Model field `superscript_citations` → Task 2. ✓
- Per-run superscript detection, body-only, faithful `raw_text` → Task 2 (+ affiliation exclusion, a refinement of "body only"). ✓
- Shared number-parsing helper (no divergence) → Task 1. ✓
- Pre-scan union → Task 3. ✓
- Deterministic `cited` union, `cited_square` unchanged → Task 4. ✓
- Fail-safe (superscript never filters) → Task 4 tests. ✓
- Exponent containment → Task 4 `test_superscript_exponent_cannot_hard_filter`. ✓
- Parser faithful-text criterion → Task 2 `test_superscript_citations_collected_from_body`. ✓
- Table-cell limitation → not implemented (documented in spec as out of scope). ✓

**Placeholder scan:** none — every step has concrete code/commands.

**Type consistency:** `superscript_run_citations(str) -> set[int]`, `_numbers_in_citation_group(str) -> set[int]`, `Manuscript.superscript_citations: set[int]` used consistently across Tasks 1–4.
