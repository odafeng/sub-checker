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
