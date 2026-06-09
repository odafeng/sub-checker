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


class Config(BaseModel):
    manuscript: str | None = None
    language: str = "en-US"
    journal: str | None = None
    model: str = "claude-opus-4-8"
    output_lang: str = "en"  # "en" or "zh-TW" — language for agent findings output
    cot_dir: str | None = (
        None  # COT log directory. None = default (~/.sub-checker/cot). "disabled" = no COT.
    )
    figures: FigureConfig = Field(default_factory=FigureConfig)
    claim: ClaimConfig = Field(default_factory=ClaimConfig)
    custom_dictionary: list[str] = Field(default_factory=list)


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

# Model for checker agents
model: "claude-opus-4-8"

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
