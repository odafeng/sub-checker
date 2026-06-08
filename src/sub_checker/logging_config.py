"""Logging configuration with automatic rotation and agent chain-of-thought tracking.

COT logs may contain manuscript excerpts (tool call results). By default they are stored
in ~/.sub-checker/cot/. Set cot_dir=None to disable COT file logging entirely.
The directory is configurable via setup_logging(log_dir=...) and AgentCOTLogger(cot_dir=...).
"""

from __future__ import annotations

import json
import logging
import logging.handlers
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_DEFAULT_LOG_DIR = Path.home() / ".sub-checker" / "logs"
_DEFAULT_COT_DIR = Path.home() / ".sub-checker" / "cot"


def setup_logging(verbose: bool = False, log_dir: Path | None = None) -> None:
    """Set up logging with file rotation and optional verbose console output."""
    log_dir = log_dir or _DEFAULT_LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger("sub_checker")
    root.setLevel(logging.DEBUG)

    # Avoid duplicate handlers on repeated calls
    if root.handlers:
        return

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "sub-checker.log",
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(file_handler)

    error_handler = logging.handlers.RotatingFileHandler(
        log_dir / "sub-checker.error.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(name)s | %(levelname)s | %(message)s\n%(exc_info)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    root.addHandler(error_handler)

    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(logging.Formatter("%(levelname)s | %(name)s | %(message)s"))
    root.addHandler(console)


class AgentCOTLogger:
    """Logs each agent's chain-of-thought to a JSON file.

    Set cot_dir=None to disable file output (entries are still kept in memory
    and available via .entries for testing).
    """

    def __init__(self, agent_name: str, run_id: str, cot_dir: Path | None = _DEFAULT_COT_DIR):
        self.agent_name = agent_name
        self.run_id = run_id
        self._cot_dir = cot_dir
        self._entries: list[dict[str, Any]] = []
        self._logger = logging.getLogger(f"sub_checker.agent.{agent_name}")

        if cot_dir is not None:
            cot_dir.mkdir(parents=True, exist_ok=True)

    @property
    def entries(self) -> list[dict[str, Any]]:
        """Read-only access to logged entries (useful for testing)."""
        return list(self._entries)

    def log_request(self, messages: list, tools: list) -> None:
        entry = {
            "type": "api_request",
            "timestamp": datetime.now(UTC).isoformat(),
            "message_count": len(messages),
            "tool_count": len(tools),
        }
        self._entries.append(entry)
        self._logger.debug("API request: %d messages, %d tools", len(messages), len(tools))

    def log_response(self, stop_reason: str, content_blocks: list) -> None:
        blocks_summary = []
        for block in content_blocks:
            if hasattr(block, "type"):
                if block.type == "tool_use":
                    blocks_summary.append(
                        {"type": "tool_use", "tool": block.name, "input": block.input}
                    )
                elif block.type == "text":
                    blocks_summary.append({"type": "text", "text": block.text[:500]})

        entry = {
            "type": "api_response",
            "timestamp": datetime.now(UTC).isoformat(),
            "stop_reason": stop_reason,
            "content_blocks": blocks_summary,
        }
        self._entries.append(entry)
        self._logger.debug(
            "API response: stop_reason=%s, blocks=%d", stop_reason, len(blocks_summary)
        )

    def log_tool_result(self, tool_name: str, tool_id: str, result: str) -> None:
        entry = {
            "type": "tool_result",
            "timestamp": datetime.now(UTC).isoformat(),
            "tool_name": tool_name,
            "tool_id": tool_id,
            "result_preview": result[:500],
        }
        self._entries.append(entry)
        self._logger.debug("Tool result [%s]: %s", tool_name, result[:200])

    def log_finding(self, severity: str, message: str) -> None:
        entry = {
            "type": "finding",
            "timestamp": datetime.now(UTC).isoformat(),
            "severity": severity,
            "message": message,
        }
        self._entries.append(entry)
        self._logger.info("Finding [%s]: %s", severity, message)

    def log_error(self, error: str, exc_info: Exception | None = None) -> None:
        entry = {
            "type": "error",
            "timestamp": datetime.now(UTC).isoformat(),
            "error": error,
        }
        self._entries.append(entry)
        self._logger.error("Agent error: %s", error, exc_info=exc_info)

    def save(self) -> Path | None:
        """Save COT log to file. Returns None if cot_dir is disabled."""
        if self._cot_dir is None:
            return None

        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        filename = f"{timestamp}_{self.run_id}_{self.agent_name}.json"
        filepath = self._cot_dir / filename

        data = {
            "agent": self.agent_name,
            "run_id": self.run_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "entries": self._entries,
            "total_steps": len(self._entries),
        }

        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        self._logger.info("COT log saved: %s", filepath)
        return filepath
