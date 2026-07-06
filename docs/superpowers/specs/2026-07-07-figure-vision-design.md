# Figure vision check (content vs legend + panel completeness)

**Date:** 2026-07-07
**Status:** Approved (design)
**Scope:** "B / V1" — a non-agentic vision pass that compares each separately-
supplied figure image against its legend. Two checks: (1) content-vs-legend
mismatch, (2) panel completeness.

## Problem

Journal submissions ship figures as **separate image files** (PNG/TIFF), not
embedded in the `.docx`. The tool already knows this — `parse_docx` takes a
`figure_dir`, and `list_figures` / `check_file_exists` enumerate it — but it
only ever checks that files **exist**; it never looks at their **content**. So
mismatches between a figure and its legend (e.g. "Figure 2. CT of the pelvis"
over an MRI image) and missing panels (legend describes panels A–D, image has
A–C) are invisible.

## Goal (verifiable behavior change)

For each figure file that has a findable legend, a single vision request
compares the image to its legend and reports:
- `content_mismatch` — the image contradicts the legend (modality, colour,
  orientation, stain, count, etc.);
- `panel_incomplete` — panels named in the legend are missing from the image
  (or the image has panels the legend never names).

Non-goals (V1): legibility/quality/resolution judgments (subjective, deferred);
EPS/PDF figures (deferred — PNG/TIFF only); any change to the agentic loop.

## Architecture: standalone non-agentic checker

A new `FigureVisionChecker` (in `src/sub_checker/vision/figure_review.py`) with
the duck-typed checker interface (`name`, `model`, `async run(manuscript,
config) -> CheckerResult`) so it slots into the orchestrator's Phase-1 fan-out
alongside the agent checkers — **without touching `base.py`'s agentic loop.**

`run()`:
1. If `manuscript.figure_dir` is missing/empty or `config.figures.vision_enabled`
   is False → return an empty `CheckerResult` (zero API calls).
2. Enumerate image files (`.png/.jpg/.jpeg/.gif/.webp/.tif/.tiff`), capped at
   `_MAX_FIGURES = 20` (log if exceeded).
3. For each file, derive its figure number from the filename (`Figure3.png` → 3)
   and extract that figure's legend from `manuscript.raw_text`. No legend found
   → skip (missing legends are `figure_table`'s job, not ours).
4. Load the image (see Image loading) and issue **one** vision request per
   figure, concurrently under a semaphore (`_MAX_CONCURRENT = 3`).
5. Collect findings; return one `CheckerResult` (checker `"figure_vision"`,
   `model` = the vision model, aggregated `token_usage`).

### Findings skip the text reviewer

Every vision finding is created with `validation_status="confirmed"` and a
`validation_note="[figure_vision] not text-reviewable"`. The text reviewer only
processes `""`/`"downgraded"` findings, so it will not try (and fail) to verify
an image finding it cannot see — consistent with the existing "pre-confirmed
notice" pattern (`base.py._note_incomplete`). `claim_type` is left `None`; the
deterministic date/citation validators key off other fields and will not match.

## Image loading (`src/sub_checker/vision/image_loader.py`)

`load_image_block(path: Path) -> dict | None` returns an Anthropic image content
block `{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}`,
or `None` with a reason:

- `.png/.jpg/.jpeg/.gif/.webp` → read bytes, base64, native media type. **No
  Pillow, no client-side resize** — the Anthropic API downsamples server-side
  and bills by the resized size, so per-image cost is inherently bounded.
- `.tif/.tiff` → needs Pillow (optional `[vision]` extra). If Pillow is present,
  open → convert to RGB if needed → save as PNG in-memory → base64. If Pillow is
  absent, return a sentinel so `run()` emits one INFO finding: "install
  sub-checker[vision] to check TIFF figures" (never crash).
- unknown extension → `None` + skip.

Split loader from checker so image handling is testable without the API.

## Output tool

`report_figure_findings` (forced-schema, mirrors the reviewer's
`submit_verdicts`): `{ findings: [ { issue_type: "content_mismatch" |
"panel_incomplete", severity: "error"|"warning"|"info", message, suggestion,
confidence } ] }`. The prompt instructs: report ONLY genuine mismatches; an
image that matches its legend yields an empty list. Text-JSON fallback kept for
robustness, as in the reviewer.

## Config, deps, wiring

- `config.py`: `FigureConfig.vision_enabled: bool = True`; add the line to
  `DEFAULT_CONFIG_YAML`. Model resolves via `config.model_for("figure_vision")`
  (unlisted → global `model`; override in `models:` to use e.g. Sonnet).
- `pyproject.toml`: new optional extra `[project.optional-dependencies] vision = ["pillow>=10.0"]`.
- `orchestrator.create_agents`: append `FigureVisionChecker(model=config.model_for("figure_vision"))`
  when `config.figures.vision_enabled` (runtime no-op without figures, so
  unconditional creation is safe). It participates in the Phase-1 semaphore.
- `i18n.py`: add `checker_figure_vision` ("Figure Vision" / "圖像內容檢查") to both locales.
- `api.py`: add `figure_vision` to `ALL_CHECKERS` for the web GUI selector.
- Cost: `build_report` already costs per `result.model`; no change needed.

## Testing

1. **Legend extraction** (`extract_figure_legend(raw_text, n)`): pulls "Figure 2.
   …" up to the next "Figure 3"/end; returns `""` when absent.
2. **image_loader:** PNG → block with `media_type=image/png`; unknown ext → None;
   TIFF → PNG block (guarded by `pytest.importorskip("PIL")`); TIFF w/o Pillow →
   sentinel (simulate via monkeypatched import flag).
3. **Checker with mocked API** (mirror reviewer tests / `mock_helpers`): a figure
   + legend + a mocked `report_figure_findings` tool call → `CheckerResult` with
   the finding, `validation_status=="confirmed"`, checker `"figure_vision"`.
4. **No-op paths:** no `figure_dir` → empty result, **zero** API calls;
   `vision_enabled=False` → not created / empty.
5. **Reviewer isolation:** a confirmed figure_vision finding passed through
   `run_reviewer` is left untouched (already covered by reviewer's status filter;
   add one explicit assertion).
6. **Real smoke test (manual, gated):** a generated PNG whose rendered text says
   "MRI" with a legend claiming "CT" → the real vision model returns a
   `content_mismatch`. Run once during verification (ANTHROPIC_API_KEY present),
   not in CI.

## Files

| File | Change |
|------|--------|
| `src/sub_checker/vision/__init__.py` | new package |
| `src/sub_checker/vision/image_loader.py` | new: `load_image_block`, media-type map, TIFF→PNG |
| `src/sub_checker/vision/figure_review.py` | new: `FigureVisionChecker`, `extract_figure_legend`, output tool, vision call |
| `src/sub_checker/config.py` | `FigureConfig.vision_enabled`; YAML line |
| `src/sub_checker/orchestrator.py` | conditionally append the checker |
| `src/sub_checker/i18n.py` | `checker_figure_vision` label (en/zh-TW) |
| `src/sub_checker/api.py` | add to `ALL_CHECKERS` |
| `pyproject.toml` | `[vision]` extra → pillow |
| `tests/test_vision.py` (+ helpers) | loader, legend, mocked-checker, no-op, reviewer-isolation |

## Known limitations (documented, not fixed)
- EPS/PDF figures unsupported in V1.
- Legend extraction is regex-based ("Figure N …"); unusual legend layouts may not
  match → that figure is skipped (never mis-reported).
- Table images / multi-figure composite files keyed only by the first number in
  the filename.
