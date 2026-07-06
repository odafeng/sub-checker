"""Tests for the figure vision checker and image loader."""

from __future__ import annotations

import base64
import builtins
from pathlib import Path

import pytest

from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.vision.figure_review import FigureVisionChecker, extract_figure_legend
from sub_checker.vision.image_loader import TIFF_NEEDS_PILLOW, load_image_block
from tests.mock_helpers import MockResponse, MockToolUse, mock_anthropic_client

_VISION_TARGET = "sub_checker.vision.figure_review.anthropic.AsyncAnthropic"


def test_load_png_returns_native_block(tmp_path: Path):
    p = tmp_path / "Figure1.png"
    p.write_bytes(b"\x89PNG fake bytes")
    block = load_image_block(p)
    assert isinstance(block, dict)
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
    assert isinstance(block, dict)
    assert block["source"]["media_type"] == "image/png"


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


async def test_figure_vision_no_figures_makes_no_api_call():
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
