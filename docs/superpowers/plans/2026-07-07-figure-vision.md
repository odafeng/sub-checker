# Figure Vision Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A non-agentic `FigureVisionChecker` that sends each separately-supplied figure image + its legend to a vision model once, reporting content-vs-legend mismatches and panel incompleteness.

**Architecture:** New `sub_checker.vision` package (`image_loader`, `figure_review`). The checker exposes the duck-typed checker interface and joins the orchestrator's Phase-1 fan-out via a new `Checker` Protocol — `base.py` is untouched. Findings are pre-`confirmed` so the text reviewer (blind to images) skips them.

**Tech Stack:** Python 3.11+, anthropic SDK (vision), Pillow (optional, TIFF only), pytest (asyncio auto).

## Global Constraints

- Python floor 3.11; `from __future__ import annotations` in every new module.
- ruff (E,W,F,I,N,UP,B,SIM,RUF; E501 ignored) + `ruff format`; pyright basic 0 errors.
- No client-side image resize (API bounds cost); Pillow only for TIFF, via optional `[vision]` extra; never crash when Pillow absent.
- Vision findings: `validation_status="confirmed"`, `checker="figure_vision"`, `claim_type=None`.
- Caps: `_MAX_FIGURES = 20`, `_MAX_CONCURRENT = 3`.
- Model via `config.model_for("figure_vision")` (global model unless overridden).

---

### Task 1: Image loader

**Files:**
- Create: `src/sub_checker/vision/__init__.py` (empty)
- Create: `src/sub_checker/vision/image_loader.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces: `load_image_block(path: Path) -> dict | str | None` — Anthropic image content block, or `TIFF_NEEDS_PILLOW` (str sentinel), or `None`. Constant `TIFF_NEEDS_PILLOW: str`.

- [ ] **Step 1: Write the failing tests** (`tests/test_vision.py`)

```python
"""Tests for the figure vision checker and image loader."""

from __future__ import annotations

import base64
import builtins
from pathlib import Path

import pytest

from sub_checker.vision.image_loader import TIFF_NEEDS_PILLOW, load_image_block


def test_load_png_returns_native_block(tmp_path: Path):
    p = tmp_path / "Figure1.png"
    p.write_bytes(b"\x89PNG fake bytes")
    block = load_image_block(p)
    assert block["type"] == "image"
    assert block["source"]["media_type"] == "image/png"
    assert base64.standard_b64decode(block["source"]["data"]) == b"\x89PNG fake bytes"


def test_load_unknown_extension_returns_none(tmp_path: Path):
    p = tmp_path / "Figure1.eps"
    p.write_bytes(b"%!PS")
    assert load_image_block(p) is None


def test_load_tiff_without_pillow_returns_sentinel(tmp_path: Path, monkeypatch):
    p = tmp_path / "Figure1.tiff"
    p.write_bytes(b"II*\x00")
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "PIL" or name.startswith("PIL."):
            raise ImportError("no PIL")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    assert load_image_block(p) == TIFF_NEEDS_PILLOW


def test_load_tiff_with_pillow_converts_to_png(tmp_path: Path):
    pytest.importorskip("PIL")
    from PIL import Image

    p = tmp_path / "Figure1.tif"
    Image.new("RGB", (2, 2), "white").save(p)
    block = load_image_block(p)
    assert block["source"]["media_type"] == "image/png"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vision.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sub_checker.vision'`

- [ ] **Step 3: Create the package + loader**

`src/sub_checker/vision/__init__.py`: empty file.

`src/sub_checker/vision/image_loader.py`:

```python
"""Load figure image files as Anthropic vision content blocks."""

from __future__ import annotations

import base64
from io import BytesIO
from pathlib import Path

_NATIVE_MEDIA_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}
_TIFF_EXTS = {".tif", ".tiff"}

# Returned when a TIFF is found but Pillow (the [vision] extra) isn't installed.
TIFF_NEEDS_PILLOW = "tiff_needs_pillow"


def _block(media_type: str, data: bytes) -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


def load_image_block(path: Path) -> dict | str | None:
    """Return an Anthropic image content block for a figure file.

    - supported raster image -> content block dict
    - TIFF but no Pillow -> TIFF_NEEDS_PILLOW
    - unsupported extension or read/convert error -> None

    No client-side resize: the Anthropic API downsamples server-side and bills
    by the resized size, so per-image cost is already bounded.
    """
    ext = path.suffix.lower()
    if ext in _NATIVE_MEDIA_TYPES:
        try:
            return _block(_NATIVE_MEDIA_TYPES[ext], path.read_bytes())
        except OSError:
            return None
    if ext in _TIFF_EXTS:
        try:
            from PIL import Image
        except ImportError:
            return TIFF_NEEDS_PILLOW
        try:
            with Image.open(path) as img:
                rgb = img if img.mode in ("RGB", "L") else img.convert("RGB")
                buf = BytesIO()
                rgb.save(buf, format="PNG")
            return _block("image/png", buf.getvalue())
        except OSError:
            return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vision.py -v`
Expected: PASS (TIFF-with-Pillow test skips if Pillow absent)

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/vision/__init__.py src/sub_checker/vision/image_loader.py tests/test_vision.py
git commit -m "feat: figure image loader (png/jpeg native, tiff via optional pillow)"
```

---

### Task 2: Figure-legend extraction

**Files:**
- Create: `src/sub_checker/vision/figure_review.py` (start with just the helper)
- Test: `tests/test_vision.py`

**Interfaces:**
- Produces: `extract_figure_legend(raw_text: str, number: int) -> str` — the legend block for figure `number`, or `""`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_vision.py`)

```python
from sub_checker.vision.figure_review import extract_figure_legend


def test_extract_figure_legend_picks_legend_block():
    text = (
        "As shown in Figure 2, the mass is large.\n\n"
        "Figure 2. CT of the pelvis showing a 3 cm rectal tumour (arrow).\n\n"
        "Figure 3. Kaplan-Meier survival curve."
    )
    legend = extract_figure_legend(text, 2)
    assert "CT of the pelvis" in legend
    assert "Kaplan-Meier" not in legend


def test_extract_figure_legend_absent_returns_empty():
    assert extract_figure_legend("No figures mentioned here.", 1) == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vision.py -k legend -v`
Expected: FAIL — `ImportError: cannot import name 'extract_figure_legend'`

- [ ] **Step 3: Create `figure_review.py` with the helper**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vision.py -k legend -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/vision/figure_review.py tests/test_vision.py
git commit -m "feat: extract figure legend block from manuscript text"
```

---

### Task 3: FigureVisionChecker (vision call, mocked)

**Files:**
- Modify: `src/sub_checker/vision/figure_review.py`
- Test: `tests/test_vision.py`

**Interfaces:**
- Consumes: `load_image_block`, `TIFF_NEEDS_PILLOW` (Task 1); `extract_figure_legend` (Task 2); `mock_anthropic_client`, `MockResponse`, `MockToolUse` from `tests/mock_helpers.py`.
- Produces: `class FigureVisionChecker` with `name = "figure_vision"`, `model: str`, `async run(manuscript, config) -> CheckerResult`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_vision.py`)

```python
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.vision.figure_review import FigureVisionChecker
from tests.mock_helpers import MockResponse, MockToolUse, mock_anthropic_client

_VISION_TARGET = "sub_checker.vision.figure_review.anthropic.AsyncAnthropic"


def _ms_with_fig(tmp_path: Path, legend: str) -> Manuscript:
    (tmp_path / "Figure1.png").write_bytes(b"\x89PNG fake")
    return Manuscript(
        title="T", sections=[], paragraphs=[], raw_text=legend, figure_dir=tmp_path
    )


async def test_figure_vision_reports_mismatch(tmp_path: Path):
    ms = _ms_with_fig(tmp_path, "Figure 1. CT of the pelvis.")
    resp = MockResponse(
        content=[
            MockToolUse(
                name="report_figure_findings",
                input={
                    "findings": [
                        {
                            "issue_type": "content_mismatch",
                            "severity": "warning",
                            "message": "Legend says CT but the image is an MRI.",
                            "suggestion": "Correct the modality.",
                            "confidence": 0.9,
                        }
                    ]
                },
            )
        ],
        stop_reason="tool_use",
    )
    with mock_anthropic_client(resp, target=_VISION_TARGET):
        result = await FigureVisionChecker().run(ms, Config(cot_dir="disabled"))

    assert len(result.findings) == 1
    f = result.findings[0]
    assert f.checker == "figure_vision"
    assert f.validation_status == "confirmed"
    assert "MRI" in f.message
    assert "Figure 1" in (f.location or "")


async def test_figure_vision_no_figures_makes_no_api_call(tmp_path: Path):
    ms = Manuscript(title="T", sections=[], paragraphs=[], raw_text="x", figure_dir=None)
    # No mock installed: any real API call would raise. It must not call.
    result = await FigureVisionChecker().run(ms, Config(cot_dir="disabled"))
    assert result.findings == []
    assert result.checker_name == "figure_vision"


async def test_figure_vision_disabled_makes_no_api_call(tmp_path: Path):
    ms = _ms_with_fig(tmp_path, "Figure 1. CT of the pelvis.")
    cfg = Config(cot_dir="disabled")
    cfg.figures.vision_enabled = False
    result = await FigureVisionChecker().run(ms, cfg)
    assert result.findings == []


async def test_figure_vision_skips_figure_without_legend(tmp_path: Path):
    # Figure file exists but no matching legend in text -> skip, no API call.
    ms = _ms_with_fig(tmp_path, "This manuscript mentions no figure legends.")
    result = await FigureVisionChecker().run(ms, Config(cot_dir="disabled"))
    assert result.findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_vision.py -k figure_vision -v`
Expected: FAIL — `ImportError: cannot import name 'FigureVisionChecker'`

- [ ] **Step 3: Implement the checker** (append to `figure_review.py`)

Add imports at the top of `figure_review.py` (below the existing `import re`):

```python
import asyncio
import logging
import time

import anthropic

from sub_checker.agents.base import supports_adaptive_thinking
from sub_checker.config import Config
from sub_checker.models import CheckerResult, Finding, Manuscript, Severity, TokenUsage
from sub_checker.vision.image_loader import TIFF_NEEDS_PILLOW, load_image_block

logger = logging.getLogger("sub_checker.vision.figure_review")

_MAX_FIGURES = 20
_MAX_CONCURRENT = 3
_MAX_TOKENS = 2048
_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff"}
_SEVERITY = {"error": Severity.ERROR, "warning": Severity.WARNING, "info": Severity.INFO}

_REPORT_TOOL = {
    "name": "report_figure_findings",
    "description": "Report mismatches between a figure image and its legend. Call once.",
    "input_schema": {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "issue_type": {
                            "type": "string",
                            "enum": ["content_mismatch", "panel_incomplete"],
                        },
                        "severity": {"type": "string", "enum": ["error", "warning", "info"]},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                        "confidence": {"type": "number"},
                    },
                    "required": ["issue_type", "severity", "message"],
                },
            }
        },
        "required": ["findings"],
    },
}

_SYSTEM_PROMPT = """\
You compare a single scientific figure image against its legend text.

Report ONLY genuine problems, via report_figure_findings:
- content_mismatch: the image contradicts the legend (wrong modality e.g. CT vs
  MRI, wrong stain, wrong colour/orientation, a described feature absent, counts
  that disagree).
- panel_incomplete: panels named in the legend (A, B, C, ...) are missing from
  the image, or the image has lettered panels the legend never describes.

If the image is consistent with its legend, return an empty findings list. Do
not invent problems. Judge only what the legend claims vs what the image shows.
Always call report_figure_findings exactly once."""


def _figure_number(path: Path) -> int | None:
    m = re.search(r"\d+", path.stem)
    return int(m.group()) if m else None


class FigureVisionChecker:
    """Vision pass comparing each figure file to its legend. Non-agentic."""

    name = "figure_vision"

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model

    async def run(self, manuscript: Manuscript, config: Config) -> CheckerResult:
        start = time.monotonic()
        fig_dir = manuscript.figure_dir
        if not config.figures.vision_enabled or fig_dir is None or not fig_dir.exists():
            return CheckerResult(checker_name=self.name, model=self.model)

        files = sorted(f for f in fig_dir.iterdir() if f.suffix.lower() in _IMAGE_EXTS)
        if len(files) > _MAX_FIGURES:
            logger.warning(
                "figure_vision: %d figures found, capping at %d", len(files), _MAX_FIGURES
            )
            files = files[:_MAX_FIGURES]
        if not files:
            return CheckerResult(checker_name=self.name, model=self.model)

        usage = TokenUsage()
        sem = asyncio.Semaphore(_MAX_CONCURRENT)

        async with anthropic.AsyncAnthropic() as client:

            async def one(path: Path) -> list[Finding]:
                async with sem:
                    return await self._review_figure(client, manuscript, path, usage)

            batches = await asyncio.gather(*(one(f) for f in files))

        findings = [f for batch in batches for f in batch]
        return CheckerResult(
            checker_name=self.name,
            findings=findings,
            elapsed_seconds=time.monotonic() - start,
            token_usage=usage,
            model=self.model,
        )

    async def _review_figure(
        self,
        client: anthropic.AsyncAnthropic,
        manuscript: Manuscript,
        path: Path,
        usage: TokenUsage,
    ) -> list[Finding]:
        number = _figure_number(path)
        legend = extract_figure_legend(manuscript.raw_text, number) if number else ""
        if not legend:
            return []  # missing legends are figure_table's job, not ours

        block = load_image_block(path)
        if block == TIFF_NEEDS_PILLOW:
            return [
                self._notice(
                    f"Figure {number}: install 'sub-checker[vision]' to check TIFF "
                    f"figures ({path.name})."
                )
            ]
        if not isinstance(block, dict):
            return []

        content = [
            {
                "type": "text",
                "text": f'Figure {number} legend:\n"""\n{legend}\n"""\n\n'
                "Compare the attached image to this legend and report any mismatch.",
            },
            block,
        ]
        extra: dict = {}
        if supports_adaptive_thinking(self.model):
            extra["thinking"] = {"type": "adaptive"}

        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                system=[{"type": "text", "text": _SYSTEM_PROMPT}],
                tools=[_REPORT_TOOL],
                messages=[{"role": "user", "content": content}],
                **extra,
            )
        except anthropic.APIError as e:
            logger.error("figure_vision: API error on %s: %s", path.name, e)
            return []

        usage.input_tokens += response.usage.input_tokens
        usage.output_tokens += response.usage.output_tokens
        usage.cache_creation_input_tokens += response.usage.cache_creation_input_tokens or 0
        usage.cache_read_input_tokens += response.usage.cache_read_input_tokens or 0

        raw: list = []
        for b in response.content:
            if b.type == "tool_use" and b.name == "report_figure_findings":
                payload = b.input if isinstance(b.input, dict) else {}
                got = payload.get("findings", [])
                raw = got if isinstance(got, list) else []
                break
        return [self._to_finding(number, path, r) for r in raw if isinstance(r, dict)]

    def _to_finding(self, number: int | None, path: Path, r: dict) -> Finding:
        try:
            conf = float(r.get("confidence", 0.8))
        except (TypeError, ValueError):
            conf = 0.8
        issue = str(r.get("issue_type", "content_mismatch"))
        return Finding(
            checker=self.name,
            severity=_SEVERITY.get(str(r.get("severity", "warning")).lower(), Severity.WARNING),
            message=str(r.get("message", "")),
            location=f"Figure {number} ({path.name})",
            suggestion=r.get("suggestion"),
            confidence=conf,
            validation_status="confirmed",
            validation_note=f"[figure_vision] {issue}, not text-reviewable",
        )

    def _notice(self, message: str) -> Finding:
        return Finding(
            checker=self.name,
            severity=Severity.INFO,
            message=message,
            validation_status="confirmed",
            validation_note="[figure_vision] notice",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_vision.py -v`
Expected: PASS (all vision tests)

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/vision/figure_review.py tests/test_vision.py
git commit -m "feat: FigureVisionChecker (one vision call per figure, findings pre-confirmed)"
```

---

### Task 4: Wire into orchestrator, config, deps, i18n, api

**Files:**
- Modify: `src/sub_checker/orchestrator.py` (add `Checker` Protocol; retype; append checker)
- Modify: `src/sub_checker/pipeline.py` (retype `agents` param)
- Modify: `src/sub_checker/config.py` (`FigureConfig.vision_enabled` + YAML)
- Modify: `pyproject.toml` (`[vision]` extra)
- Modify: `src/sub_checker/i18n.py` (`checker_figure_vision`)
- Modify: `src/sub_checker/api.py` (`ALL_CHECKERS`)
- Test: `tests/test_orchestrator.py`

**Interfaces:**
- Consumes: `FigureVisionChecker` (Task 3).
- Produces: `Checker` Protocol; `create_agents` includes `figure_vision` when `config.figures.vision_enabled`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_orchestrator.py`)

```python
def test_create_agents_includes_figure_vision_by_default():
    names = [a.name for a in create_agents(Config())]
    assert "figure_vision" in names


def test_create_agents_omits_figure_vision_when_disabled():
    cfg = Config()
    cfg.figures.vision_enabled = False
    names = [a.name for a in create_agents(cfg)]
    assert "figure_vision" not in names
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orchestrator.py -k figure_vision -v`
Expected: FAIL — `figure_vision` not in the agent list

- [ ] **Step 3a: `config.py`** — add the field and YAML line.

In `class FigureConfig` add:

```python
    vision_enabled: bool = True
```

In `DEFAULT_CONFIG_YAML`, under `figures:` (after `case_sensitive: false`):

```python
  vision_enabled: true
```

- [ ] **Step 3b: `orchestrator.py`** — Protocol + wiring.

Replace the import `from sub_checker.agents.base import BaseCheckerAgent` (line ~14) with a Protocol definition. Add near the top (after the existing imports):

```python
from typing import Protocol


class Checker(Protocol):
    """Structural type for anything the orchestrator can run as a checker."""

    name: str
    model: str

    async def run(self, manuscript: Manuscript, config: Config) -> CheckerResult: ...
```

Then replace every `BaseCheckerAgent` annotation with `Checker`:
- `def create_agents(config: Config) -> list[Checker]:`
- `def filter_agents(agents: list[Checker], ... ) -> list[Checker]:`
- `agent: Checker,` in `run_agent_safe`
- `agents: list[Checker],` in `run_all_phases`
- `async def run_limited(agent: Checker) -> CheckerResult:`

Change the body of `create_agents` (the `return` line) to append the vision checker:

```python
    if not config.claim.enabled:
        classes = [c for c in classes if c is not CitationClaimAgent]
    agents: list[Checker] = [cls(model=config.model_for(cls.name)) for cls in classes]
    if config.figures.vision_enabled:
        from sub_checker.vision.figure_review import FigureVisionChecker

        agents.append(FigureVisionChecker(model=config.model_for("figure_vision")))
    return agents
```

- [ ] **Step 3c: `pipeline.py`** — retype.

Replace `from sub_checker.agents.base import BaseCheckerAgent` with:

```python
from sub_checker.orchestrator import Checker
```

and change `agents: list[BaseCheckerAgent],` to `agents: list[Checker],`. (The other orchestrator imports on the existing `from sub_checker.orchestrator import ...` line stay; add `Checker` there instead if you prefer a single import line.)

- [ ] **Step 3d: `i18n.py`** — add to BOTH locales' checker-name blocks:

```python
        "checker_figure_vision": "Figure Vision",
```

(en) and

```python
        "checker_figure_vision": "圖像內容檢查",
```

(zh-TW).

- [ ] **Step 3e: `api.py`** — add to `ALL_CHECKERS` list:

```python
    {"name": "figure_vision", "label_en": "Figure Vision", "label_zh": "圖像內容檢查"},
```

- [ ] **Step 3f: `pyproject.toml`** — add the optional extra under `[project.optional-dependencies]`:

```toml
vision = [
    "pillow>=10.0",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/sub_checker/orchestrator.py src/sub_checker/pipeline.py src/sub_checker/config.py src/sub_checker/i18n.py src/sub_checker/api.py pyproject.toml tests/test_orchestrator.py
git commit -m "feat: wire figure_vision checker into orchestrator/config/i18n/api"
```

---

### Task 5: Full gate + real vision smoke test

**Files:** none (verification only)

- [ ] **Step 1: Full local gate**

```bash
python -m pytest -q
python -m ruff check . && python -m ruff format --check . && python -m pyright
```
Expected: all pass, 0 pyright errors. (If `ruff format` rewrites files, re-add and amend the last commit.)

- [ ] **Step 2: Real end-to-end vision smoke test** (proves the image pipeline reaches the model; needs `ANTHROPIC_API_KEY`, which is present)

```bash
python -m pip install "pillow>=10.0" -q
python - <<'PY'
import asyncio
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.vision.figure_review import FigureVisionChecker

d = Path(tempfile.mkdtemp())
img = Image.new("RGB", (400, 200), "black")
ImageDraw.Draw(img).text((20, 90), "MRI SCAN", fill="white")
img.save(d / "Figure1.png")

ms = Manuscript(title="T", sections=[], paragraphs=[], raw_text=
    "Figure 1. CT scan of the abdomen showing the lesion.", figure_dir=d)

res = asyncio.run(FigureVisionChecker().run(ms, Config(cot_dir="disabled")))
print("findings:", len(res.findings))
for f in res.findings:
    print(" -", f.severity.value, f.message)
assert res.findings, "expected the model to flag CT-vs-MRI mismatch"
print("SMOKE TEST PASSED")
PY
```
Expected: at least one finding mentioning the modality mismatch; prints `SMOKE TEST PASSED`.

- [ ] **Step 3: Run pre-commit (CI parity)**

```bash
git add -A && pre-commit run --all-files
```
Expected: ruff, ruff-format, pyright all Pass.

---

## Self-Review

**Spec coverage:**
- Non-agentic checker, duck-typed into fan-out, base.py untouched → Task 3 + Task 4 (`Checker` Protocol). ✓
- Content_mismatch + panel_incomplete via one vision call/figure → Task 3 (`_REPORT_TOOL`, `_SYSTEM_PROMPT`). ✓
- Findings pre-`confirmed`, skip reviewer → Task 3 (`_to_finding`/`_notice`). ✓
- PNG native / TIFF via optional Pillow / no client resize → Task 1. ✓
- Legend extraction, skip when absent → Task 2 + Task 3. ✓
- Caps `_MAX_FIGURES`/`_MAX_CONCURRENT`, no-op without figures → Task 3. ✓
- config toggle + model_for + YAML → Task 4. ✓
- pyproject `[vision]` extra → Task 4. ✓
- i18n + api ALL_CHECKERS → Task 4. ✓
- Real smoke test → Task 5. ✓

**Placeholder scan:** none — every code step is complete.

**Type consistency:** `load_image_block(Path) -> dict | str | None`, `TIFF_NEEDS_PILLOW`, `extract_figure_legend(str, int) -> str`, `FigureVisionChecker.run(Manuscript, Config) -> CheckerResult`, `Checker` Protocol used consistently across Tasks 1–4.
