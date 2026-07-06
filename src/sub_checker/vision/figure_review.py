"""Non-agentic vision check: compare each figure image to its legend."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from pathlib import Path
from typing import Any

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

_FIG_LABEL = r"(?:Figure|Fig\.?)\s*"

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
        extra: dict[str, Any] = {}
        if supports_adaptive_thinking(self.model):
            extra["thinking"] = {"type": "adaptive"}

        try:
            response = await client.messages.create(
                model=self.model,
                max_tokens=_MAX_TOKENS,
                system=[{"type": "text", "text": _SYSTEM_PROMPT}],
                tools=[_REPORT_TOOL],  # type: ignore[list-item]
                messages=[{"role": "user", "content": content}],  # type: ignore[arg-type]
                **extra,
            )
        except anthropic.APIError as e:
            logger.error("figure_vision: API error on %s: %s", path.name, e)
            return []

        usage.input_tokens += response.usage.input_tokens
        usage.output_tokens += response.usage.output_tokens
        usage.cache_creation_input_tokens += response.usage.cache_creation_input_tokens or 0
        usage.cache_read_input_tokens += response.usage.cache_read_input_tokens or 0

        raw: list[Any] = []
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
