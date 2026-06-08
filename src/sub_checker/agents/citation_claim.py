from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.services.pubmed import PubMedClient
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    get_reference_list,
    read_section,
)
from sub_checker.tools.pubmed_tools import (
    TOOL_GET_ABSTRACT,
    TOOL_SEARCH_PUBMED,
    get_abstract,
    search_pubmed,
)


class CitationClaimAgent(BaseCheckerAgent):
    name = "citation_claim"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None
        self._pubmed: PubMedClient | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are a citation verification expert. Your job is to:\n"
            "1. Read through the manuscript to find claims supported by citations\n"
            "2. For each key citation, search PubMed to find the referenced paper\n"
            "3. Read the abstract of the cited paper\n"
            "4. Judge whether the abstract supports the claim made in the manuscript:\n"
            "   - SUPPORTS: The abstract clearly supports the claim\n"
            "   - CONTRADICTS: The abstract contradicts the claim (severity=error)\n"
            "   - INSUFFICIENT: The abstract doesn't contain enough info to judge (severity=warning)\n"
            "   - NOT_FOUND: Paper not found on PubMed (severity=warning)\n\n"
            "Focus on the most important claims (results, conclusions). "
            "You don't need to verify every single citation — prioritize claims that are "
            "central to the paper's argument.\n\n"
            "Use add_finding for each problematic citation."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_REFERENCE_LIST,
            TOOL_SEARCH_PUBMED,
            TOOL_GET_ABSTRACT,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "get_reference_list":
            return get_reference_list(ms)
        if tool_name == "search_pubmed":
            assert self._pubmed is not None
            return await search_pubmed(
                self._pubmed,
                tool_input["author"],
                tool_input["year"],
                tool_input.get("title_keywords", ""),
            )
        if tool_name == "get_abstract":
            assert self._pubmed is not None
            return await get_abstract(self._pubmed, tool_input["pmid"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        self._pubmed = PubMedClient(
            email=config.claim.pubmed_email,
            api_key=config.claim.pubmed_api_key,
            max_concurrent=config.claim.max_concurrent_pubmed,
        )
        try:
            return await super().run(manuscript, config)
        finally:
            await self._pubmed.close()
