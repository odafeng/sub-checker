from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.tools.manuscript_tools import (
    TOOL_READ_PARAGRAPH,
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    read_paragraph,
    read_section,
    search_text,
)


class TypoGrammarAgent(BaseCheckerAgent):
    name = "typo_grammar"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are an academic English proofreader. Your job is to:\n"
            "1. Read through each section of the manuscript carefully\n"
            "2. Identify spelling errors, typos, and grammatical mistakes\n"
            "3. Flag awkward phrasing or non-standard academic English\n"
            "4. Skip the reference list section (reference formatting is handled by another agent)\n"
            "5. Be aware that scientific terms, gene names, chemical names, etc. are NOT typos\n\n"
            "Use add_finding for each issue. Include the incorrect text in 'context' "
            "and the suggested correction in 'suggestion'."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_READ_PARAGRAPH,
            TOOL_SEARCH_TEXT,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "read_paragraph":
            return read_paragraph(ms, tool_input["index"])
        if tool_name == "search_text":
            return search_text(ms, tool_input["query"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        return await super().run(manuscript, config)
