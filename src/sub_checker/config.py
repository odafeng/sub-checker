from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class FigureConfig(BaseModel):
    dir: str = "figures/"
    pattern: str = "Figure{n}.png"
    case_sensitive: bool = False


class ClaimConfig(BaseModel):
    enabled: bool = True
    model: str = "claude-opus-4-8"
    pubmed_email: str | None = None
    pubmed_api_key: str | None = None
    max_concurrent_pubmed: int = 3
    max_concurrent_llm: int = 5


# Mechanical checkers default to Sonnet: their work (pattern matching,
# cross-referencing, format comparison) doesn't need Opus-level reasoning,
# and the post-validation harness catches mistakes either way.
# Judgment-heavy checkers (logic, citation_claim, journal_guidelines) and
# the reviewer fall back to the global `model`.
DEFAULT_CHECKER_MODELS: dict[str, str] = {
    "typo_grammar": "claude-sonnet-4-6",
    "figure_table": "claude-sonnet-4-6",
    "citation_exist": "claude-sonnet-4-6",
    "citation_format": "claude-sonnet-4-6",
}


class Config(BaseModel):
    manuscript: str | None = None
    language: str = "en-US"
    journal: str | None = None
    model: str = "claude-opus-4-8"  # default model for judgment-heavy agents
    models: dict[str, str] = Field(
        default_factory=lambda: dict(DEFAULT_CHECKER_MODELS)
    )  # per-checker overrides; unlisted checkers use `model`
    reviewer_model: str | None = None  # None → use `model`
    max_concurrent_agents: int = 3  # global concurrency cap for checker agents
    output_lang: str = "en"  # "en" or "zh-TW" — language for agent findings output
    cot_dir: str | None = (
        None  # COT log directory. None = default (~/.sub-checker/cot). "disabled" = no COT.
    )
    figures: FigureConfig = Field(default_factory=FigureConfig)
    claim: ClaimConfig = Field(default_factory=ClaimConfig)
    custom_dictionary: list[str] = Field(default_factory=list)

    def model_for(self, checker_name: str) -> str:
        """Resolve the model to use for a given checker."""
        return self.models.get(checker_name) or self.model


def load_config(config_path: Path | None = None) -> Config:
    """Load config from YAML file, falling back to defaults."""
    if config_path and config_path.exists():
        with open(config_path) as f:
            data = yaml.safe_load(f) or {}
        return Config(**data)
    return Config()


DEFAULT_CONFIG_YAML = """\
# sub-checker configuration

# Target journal (can also be set via --journal CLI flag)
# journal: "The Lancet"

# Default language
language: "en-US"

# Default model for judgment-heavy agents (logic, citation_claim,
# journal_guidelines) and the reviewer
model: "claude-opus-4-8"

# Per-checker model overrides. Mechanical checks run fine (and ~5x cheaper)
# on Sonnet; set to {} to run everything on `model`.
models:
  typo_grammar: "claude-sonnet-4-6"
  figure_table: "claude-sonnet-4-6"
  citation_exist: "claude-sonnet-4-6"
  citation_format: "claude-sonnet-4-6"

# Model for the post-validation reviewer agent (null → use `model`)
reviewer_model: null

# How many checker agents may run concurrently
max_concurrent_agents: 3

# Figure/Table checker
figures:
  dir: "figures/"
  pattern: "Figure{n}.png"
  case_sensitive: false

# Citation-claim verification
claim:
  enabled: true
  model: "claude-opus-4-8"
  pubmed_email: null
  pubmed_api_key: null
  max_concurrent_pubmed: 3
  max_concurrent_llm: 5

# Custom dictionary (words to ignore in typo check)
custom_dictionary: []
"""
