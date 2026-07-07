"""Minimal .env loader shared by the CLI and the API server."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv() -> None:
    """Load .env from CWD or project root, without overriding existing vars."""
    for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                # Strip optional surrounding quotes: KEY="value" / KEY='value'
                value = value.strip()
                if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)
            break
