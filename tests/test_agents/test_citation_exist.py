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
    config = Config(cot_dir="disabled")
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


def _ms(body_text: str, reference_section: str | None) -> Manuscript:
    return Manuscript(
        title="T",
        sections=[],
        paragraphs=[],
        raw_text=body_text,
        body_text=body_text,
        reference_section=reference_section,
    )


def test_prescan_flags_dangling_and_uncited_numbers():
    # [7] is cited but only 3 references exist → dangling; refs 2,3 exist but
    # are never cited → possibly uncited. The pre-scan message must surface both.
    ms = _ms("We cite [1] and [7].", reference_section="1. A.\n2. B.\n3. C.")
    msg = CitationExistAgent()._build_initial_message(ms, Config(cot_dir="disabled"))
    assert "NOT in the reference list" in msg
    assert "[7]" in msg
    assert "possibly NOT cited" in msg


def test_prescan_includes_superscript_citations():
    # Body has no bracketed citations, only a superscript "[7]"-equivalent.
    ms = _ms("Effect was large.", reference_section="1. A.\n2. B.\n3. C.")
    ms.superscript_citations = {7}
    msg = CitationExistAgent()._build_initial_message(ms, Config(cot_dir="disabled"))
    # 7 is cited (via superscript) but only 3 references exist → dangling
    assert "NOT in the reference list" in msg
    assert "[7]" in msg


def test_prescan_no_phantom_dangling_when_refs_absent():
    # With no reference list, ref_nums is empty and the guard must suppress the
    # "dangling citation" line rather than flag every cited number as dangling.
    ms = _ms("We cite [1].", reference_section=None)
    msg = CitationExistAgent()._build_initial_message(ms, Config(cot_dir="disabled"))
    assert "NOT in the reference list" not in msg


@pytest.mark.asyncio
async def test_citation_exist_all_match(sample_manuscript: Manuscript):
    """No findings when all citations match references."""
    config = Config(cot_dir="disabled")
    agent = CitationExistAgent()

    responses = [
        build_tool_response([("get_reference_list", {})]),
        build_tool_response([("read_section", {"section_name": "Introduction"})]),
        build_text_response("All citations match the reference list."),
    ]

    with mock_anthropic_client(*responses):
        result = await agent.run(sample_manuscript, config)

    assert len(result.findings) == 0
