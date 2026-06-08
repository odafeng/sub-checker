from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.services.web import WebService
from sub_checker.tools.filesystem_tools import TOOL_LIST_FIGURES, list_figures
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_METADATA,
    TOOL_READ_SECTION,
    get_metadata,
    read_section,
)
from sub_checker.tools.web_tools import (
    TOOL_FETCH_PAGE,
    TOOL_WEB_SEARCH,
    fetch_page,
    web_search,
)


class JournalGuidelinesAgent(BaseCheckerAgent):
    name = "journal_guidelines"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None
        self._web_service: WebService | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are a journal submission guidelines compliance reviewer. Your job is to:\n"
            "1. Search for the target journal's Instructions for Authors / submission guidelines\n"
            "2. Read the guidelines page to extract specific requirements\n"
            "3. Check the manuscript against ALL requirements:\n\n"
            "STRUCTURE:\n"
            "- Required sections present (Title page, Abstract, Keywords, Introduction, Methods, Results, Discussion, References)\n"
            "- Section ordering matches journal requirements\n"
            "- Title page with author info and affiliations\n\n"
            "WORD COUNTS:\n"
            "- Main text within word limit\n"
            "- Abstract within word limit\n"
            "- Title within character/word limit\n\n"
            "ABSTRACT:\n"
            "- Structured vs unstructured (as required)\n"
            "- Required sub-headings (Background/Methods/Results/Conclusions)\n\n"
            "FIGURES/TABLES:\n"
            "- Total count within journal limits\n"
            "- Figure legends in correct location\n\n"
            "REQUIRED STATEMENTS:\n"
            "- Conflict of interest / Competing interests\n"
            "- Data availability statement\n"
            "- Ethics approval / IRB statement\n"
            "- Informed consent\n"
            "- Author contributions (CRediT format if required)\n"
            "- Funding / Acknowledgements\n\n"
            "REPORTING GUIDELINES:\n"
            "- CONSORT (RCTs), STROBE (observational), PRISMA (systematic reviews), etc.\n\n"
            "Use add_finding for each non-compliance issue."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_METADATA,
            TOOL_WEB_SEARCH,
            TOOL_FETCH_PAGE,
            TOOL_LIST_FIGURES,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "get_metadata":
            return get_metadata(ms)
        if tool_name == "list_figures":
            return list_figures(ms)
        if tool_name == "web_search":
            ws = self._web_service or WebService()
            self._web_service = ws
            return await web_search(ws, tool_input["query"])
        if tool_name == "fetch_page":
            ws = self._web_service or WebService()
            self._web_service = ws
            return await fetch_page(ws, tool_input["url"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        try:
            return await super().run(manuscript, config)
        finally:
            if self._web_service:
                await self._web_service.close()
