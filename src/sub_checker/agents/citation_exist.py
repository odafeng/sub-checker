from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    get_reference_list,
    read_section,
    search_text,
)


class CitationExistAgent(BaseCheckerAgent):
    name = "citation_exist"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are a citation completeness reviewer. Your job is to:\n"
            "1. Read through the manuscript to find ALL in-text citations "
            "(e.g. '(Smith, 2020)', '(Jones et al., 2019)', etc.)\n"
            "2. Read the reference list\n"
            "3. Cross-check: every in-text citation must appear in the reference list\n"
            "4. Cross-check: every reference list entry should be cited in the text\n"
            "5. Flag mismatches in author names or years between citation and reference\n\n"
            "Use add_finding to report each issue. severity=error for missing citations, "
            "severity=warning for unreferenced entries."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_REFERENCE_LIST,
            TOOL_SEARCH_TEXT,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "get_reference_list":
            return get_reference_list(ms)
        if tool_name == "search_text":
            return search_text(ms, tool_input["query"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        return await super().run(manuscript, config)
