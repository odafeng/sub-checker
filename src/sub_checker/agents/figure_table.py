from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.tools.filesystem_tools import (
    TOOL_CHECK_FILE_EXISTS,
    TOOL_LIST_FIGURES,
    check_file_exists,
    list_figures,
)
from sub_checker.tools.manuscript_tools import (
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    read_section,
    search_text,
)


class FigureTableAgent(BaseCheckerAgent):
    name = "figure_table"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are an academic figure and table reviewer. Your job is to:\n"
            "1. Read through the manuscript to find ALL figure and table references "
            "(e.g. 'Figure 1', 'Fig. 2', 'Table 1', etc.)\n"
            "2. Check if the referenced figure files exist in the figures directory\n"
            "3. Check that numbering is sequential (no gaps)\n"
            "4. Check that all figure files are referenced in the text\n"
            "5. Check for inconsistent naming (mixing 'Figure' and 'Fig.')\n\n"
            "Use add_finding to report each issue found. Be thorough but precise."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_SEARCH_TEXT,
            TOOL_LIST_FIGURES,
            TOOL_CHECK_FILE_EXISTS,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "search_text":
            return search_text(ms, tool_input["query"])
        if tool_name == "list_figures":
            return list_figures(ms)
        if tool_name == "check_file_exists":
            return check_file_exists(ms, tool_input["filename"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        return await super().run(manuscript, config)
