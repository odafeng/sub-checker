from __future__ import annotations

from pathlib import Path

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.services.web import WebService
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    get_reference_list,
    read_section,
)
from sub_checker.tools.web_tools import (
    TOOL_FETCH_PAGE,
    TOOL_WEB_SEARCH,
    fetch_page,
    web_search,
)


class CitationFormatAgent(BaseCheckerAgent):
    name = "citation_format"
    effort = "medium"  # mechanical: pattern/cross-ref work, less thinking needed

    def __init__(self, model: str = "claude-opus-4-8"):
        super().__init__(model=model)
        self._web_service: WebService | None = None
        self._web_cache_path: Path | None = None
        self._web_cache_max_age_days = 30

    def _default_system_prompt(self) -> str:
        return (
            "You are a citation format expert. You know all major citation styles:\n"
            "- APA 7th: (Author, Year) with Author, A. A. (Year). Title. Journal, vol(issue), pp. DOI\n"
            "- Vancouver/NLM: numbered [1] or superscript, Author AA. Title. Journal. Year;vol(issue):pp.\n"
            "- AMA 11th: superscript numbers, Author AA. Title. Journal. Year;vol(issue):pp. doi:\n"
            '- Chicago Author-Date: (Author Year), Author, First. Year. "Title." Journal vol(issue): pp.\n'
            '- IEEE: [1], A. Author, "Title," Journal, vol. X, no. Y, pp., Year.\n'
            "- Harvard: (Author Year), Author, A. (Year) Title. Journal, vol(issue), pp.\n\n"
            "Your job is to:\n"
            "1. Determine the target journal's required citation format\n"
            "   - Use your built-in knowledge first\n"
            "   - If unsure, use web_search to find the journal's author guidelines\n"
            "   - Use fetch_page to read the guidelines page\n"
            "2. Check EVERY in-text citation against the required format\n"
            "3. Check EVERY reference list entry against the required format\n"
            "4. Check consistency (all entries should follow the same style)\n"
            "5. Check: author name format, punctuation, DOI/PMID inclusion, ordering\n\n"
            "IMPORTANT — DOCUMENT PARSING LIMITATIONS:\n"
            "- The manuscript text is extracted as plain text from a .docx file.\n"
            "- Superscript formatting is NOT preserved — you cannot tell whether numbers are "
            "superscript or inline. Do NOT assume superscript or claim mixed formats unless "
            "the text explicitly contains both '[1]' AND '(1)' patterns.\n"
            "- Parenthesized numbers like (1-3) are a single consistent format.\n"
            "- Reference list numbering may be stripped if the .docx uses Word auto-numbered "
            "lists. Do NOT report missing numbering as an error.\n"
            "- Vancouver format allows ALL author initials (e.g. Filho PRS for 3 given names). "
            "Do NOT claim a maximum of 2 initials.\n\n"
            "REPORTING RULES:\n"
            "- ONLY report actual problems (errors, inconsistencies, violations).\n"
            "- Do NOT report items that pass or are correct. No 'all good' findings.\n"
            "- If everything is correct, simply finish without calling add_finding."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_REFERENCE_LIST,
            TOOL_WEB_SEARCH,
            TOOL_FETCH_PAGE,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "get_reference_list":
            return get_reference_list(ms)
        if tool_name == "web_search":
            ws = self._web_service or WebService(
                cache_path=self._web_cache_path,
                cache_max_age_days=self._web_cache_max_age_days,
            )
            self._web_service = ws
            return await web_search(ws, tool_input["query"])
        if tool_name == "fetch_page":
            ws = self._web_service or WebService(
                cache_path=self._web_cache_path,
                cache_max_age_days=self._web_cache_max_age_days,
            )
            self._web_service = ws
            return await fetch_page(ws, tool_input["url"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._web_cache_path = config.web_cache_path()
        self._web_cache_max_age_days = config.web_cache_max_age_days
        try:
            return await super().run(manuscript, config)
        finally:
            if self._web_service:
                await self._web_service.close()
