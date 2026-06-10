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
    header_text: str = ""  # Raw text before first heading (title, authors, abstract, etc.)


@dataclass
class Finding:
    checker: str
    severity: Severity
    message: str
    location: str | None = None
    suggestion: str | None = None
    context: str | None = None
    # Post-validation metadata (set by Phase 3 harness)
    confidence: float = 1.0  # 0.0-1.0, set by reviewer
    validation_status: str = ""  # "confirmed", "filtered", "downgraded", ""
    validation_note: str = ""  # Reviewer's reasoning


@dataclass
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_creation_input_tokens += other.cache_creation_input_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens


@dataclass
class CheckerResult:
    checker_name: str
    findings: list[Finding] = field(default_factory=list)
    elapsed_seconds: float = 0.0
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    cot_entries: list[dict] = field(default_factory=list)


@dataclass
class Report:
    manuscript_path: str
    timestamp: datetime
    target_journal: str | None = None
    results: list[CheckerResult] = field(default_factory=list)
    summary: dict[Severity, int] = field(default_factory=dict)
    total_cost: float = 0.0
    model: str = ""
