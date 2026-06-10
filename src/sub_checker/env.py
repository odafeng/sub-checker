"""Minimal .env loader shared by the CLI and the API server."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv() -> None:
    """Load .env from CWD or project root, without overriding existing vars."""
    for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
            break
