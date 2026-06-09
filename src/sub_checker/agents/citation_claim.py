from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.services.pubmed import PubMedClient
from sub_checker.services.semantic_scholar import SemanticScholarClient
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    get_reference_list,
    read_section,
)
from sub_checker.tools.pubmed_tools import (
    TOOL_GET_ABSTRACT,
    TOOL_SEARCH_LITERATURE,
    get_abstract,
    search_literature,
)


class CitationClaimAgent(BaseCheckerAgent):
    name = "citation_claim"

    def __init__(self, model: str = "claude-opus-4-8"):
        super().__init__(model=model)
        self._manuscript: Manuscript | None = None
        self._pubmed: PubMedClient | None = None
        self._s2: SemanticScholarClient | None = None

    def _default_system_prompt(self) -> str:
        return (
            "You are a citation verification expert. Your job is to verify that EVERY "
            "citation in the manuscript is supported by the actual referenced paper.\n\n"
            "## Workflow\n\n"
            "1. Read the reference list to get all references with their details\n"
            "2. Read through each section of the manuscript\n"
            "3. For EACH citation encountered (e.g. [1], [2], (Smith, 2020)):\n"
            "   a. Identify the CLAIM being made where the citation appears\n"
            "   b. Look up the reference details from the reference list\n"
            "   c. Use search_literature to find the paper (author + year + title keywords)\n"
            "   d. Use get_abstract to retrieve the paper's abstract\n"
            "   e. Compare the claim against the abstract\n"
            "   f. Report your verdict via add_finding\n\n"
            "## Verdict Categories\n\n"
            "For EACH citation, report one of these verdicts:\n"
            "- **SUPPORTS** (severity=info): Abstract clearly supports the claim. "
            "Report as info with the evidence.\n"
            "- **PARTIALLY_SUPPORTS** (severity=info): Abstract is related but doesn't "
            "fully address the specific claim.\n"
            "- **CONTRADICTS** (severity=error): Abstract contradicts the claim.\n"
            "- **INSUFFICIENT** (severity=warning): Abstract doesn't contain enough "
            "information to verify the claim.\n"
            "- **NOT_FOUND** (severity=warning): Paper could not be found on PubMed "
            "or Semantic Scholar.\n"
            "- **NO_ABSTRACT** (severity=warning): Paper found but no abstract available.\n\n"
            "## Important Rules\n\n"
            "- You MUST verify EVERY citation, not just a sample. Work through them systematically.\n"
            "- For numbered citations like [1], [2-5], parse the reference list first to get author/title.\n"
            "- search_literature searches PubMed first, then Semantic Scholar as fallback.\n"
            "- Include the citation number, the claim text, and your verdict in each finding.\n"
            "- If multiple citations support the same claim (e.g. [2-5]), verify at least "
            "the first and last in the range.\n"
            "- For self-citations or unpublished results, report as info noting they cannot be verified.\n"
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_REFERENCE_LIST,
            TOOL_SEARCH_LITERATURE,
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
        if tool_name == "search_literature":
            assert self._pubmed is not None
            assert self._s2 is not None
            return await search_literature(
                self._pubmed,
                self._s2,
                tool_input["author"],
                tool_input["year"],
                tool_input.get("title_keywords", ""),
            )
        if tool_name == "get_abstract":
            assert self._pubmed is not None
            assert self._s2 is not None
            return await get_abstract(self._pubmed, self._s2, tool_input["paper_id"])
        return f"Unknown tool: {tool_name}"

    async def run(self, manuscript: Manuscript, config: Config):
        self._manuscript = manuscript
        self._pubmed = PubMedClient(
            email=config.claim.pubmed_email,
            api_key=config.claim.pubmed_api_key,
            max_concurrent=config.claim.max_concurrent_pubmed,
        )
        self._s2 = SemanticScholarClient(max_concurrent=3)
        try:
            return await super().run(manuscript, config)
        finally:
            await self._pubmed.close()
            await self._s2.close()
