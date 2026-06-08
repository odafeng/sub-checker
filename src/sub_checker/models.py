from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


class Severity(Enum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class Paragraph:
    text: str
    index: int
    section: str | None = None


@dataclass
class Section:
    heading: str
    level: int
    paragraphs: list[Paragraph] = field(default_factory=list)


@dataclass
class Manuscript:
    title: str
    sections: list[Section]
    paragraphs: list[Paragraph]
    raw_text: str
    reference_section: str | None = None
    figure_dir: Path | None = None


@dataclass
class Finding:
    checker: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None
    context: str | None = None


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class CheckerResult:
    checker_name: str
    findings: list[Finding] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)


@dataclass
class Report:
    manuscript_path: str
    timestamp: datetime
    target_journal: str | None = None
    results: list[CheckerResult] = field(default_factory=list)
    summary: dict[Severity, int] = field(default_factory=dict)
    total_cost: float = 0.0
