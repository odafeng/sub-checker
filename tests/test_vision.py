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
