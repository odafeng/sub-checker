"""Tests for the citation existence checker agent."""

import pytest

from sub_checker.agents.citation_exist import CitationExistAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from tests.mock_helpers import (
    build_text_response,
    build_tool_response,
    mock_anthropic_client,
)


@pytest.mark.asyncio
async def test_citation_exist_finds_missing_reference(sample_manuscript: Manuscript):
    """Agent should detect a citation with no matching reference."""
    config = Config()
    agent = CitationExistAgent()

    # Simulate: read_section(Introduction) → get_reference_list → add_finding for mismatch
    responses = [
        build_tool_response([("read_section", {"section_name": "Introduction"})]),
        build_tool_response([("get_reference_list", {})]),
        build_tool_response(
            [
                (
                    "add_finding",
                    {
                        "severity": "warning",
                        "message": "Reference 'Brown & Lee, 2021' is cited but uses '&' while reference list uses 'Brown K, Lee M.'",
                        "location": "Section: Introduction",
                    },
                )
            ]
        ),
        build_text_response("Citation check complete."),
    ]

    with mock_anthropic_client(*responses):
        result = await agent.run(sample_manuscript, config)

    assert result.checker_name == "citation_exist"
    assert len(result.findings) == 1


@pytest.mark.asyncio
async def test_citation_exist_all_match(sample_manuscript: Manuscript):
    """No findings when all citations match references."""
    config = Config()
    agent = CitationExistAgent()

    responses = [
        build_tool_response([("get_reference_list", {})]),
        build_tool_response([("read_section", {"section_name": "Introduction"})]),
        build_text_response("All citations match the reference list."),
    ]

    with mock_anthropic_client(*responses):
        result = await agent.run(sample_manuscript, config)

    assert len(result.findings) == 0
