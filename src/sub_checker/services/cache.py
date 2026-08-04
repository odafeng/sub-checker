"""Small JSON-backed cache for reusable external metadata."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class DiskCache:
    """A best-effort dict-like cache whose values must be JSON serializable."""

    def __init__(self, path: Path):
        self._path = path
        self._data: dict[str, Any] = {}
        try:
            if path.exists():
                loaded = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self._data = loaded
        except (OSError, ValueError):
            self._data = {}

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __getitem__(self, key: str) -> Any:
        return self._data[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._data[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def flush(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError:
            pass
