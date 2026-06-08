"""Tests for the figure/table checker agent."""

import pytest

from sub_checker.agents.figure_table import FigureTableAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript, Severity
from tests.mock_helpers import (
    build_text_response,
    build_tool_response,
    mock_anthropic_client,
)


@pytest.mark.asyncio
async def test_figure_table_agent_finds_missing_figure(sample_manuscript: Manuscript):
    """Agent should detect Figure3.png missing from figures dir."""
    config = Config(cot_dir="disabled")
    agent = FigureTableAgent()

    # Simulate agent: list_figures → check_file_exists(Figure3) → add_finding → done
    responses = [
        build_tool_response([("list_figures", {})]),
        build_tool_response(
            [
                ("check_file_exists", {"filename": "Figure1.png"}),
                ("check_file_exists", {"filename": "Figure2.png"}),
                ("check_file_exists", {"filename": "Figure3.png"}),
            ]
        ),
        build_tool_response(
            [
                (
                    "add_finding",
                    {
                        "severity": "error",
                        "message": "Figure 3 is referenced in the text but Figure3.png does not exist in the figures directory.",
                        "location": "Section: Results",
                        "suggestion": "Add Figure3.png to the figures directory or correct the reference.",
                    },
                )
            ]
        ),
        build_text_response("Completed figure/table check."),
    ]

    with mock_anthropic_client(*responses):
        result = await agent.run(sample_manuscript, config)

    assert result.checker_name == "figure_table"
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.ERROR
    assert "Figure 3" in result.findings[0].message


@pytest.mark.asyncio
async def test_figure_table_agent_no_issues(sample_manuscript: Manuscript):
    """Agent reports no issues when all figures exist."""
    config = Config(cot_dir="disabled")
    agent = FigureTableAgent()

    responses = [
        build_tool_response([("list_figures", {})]),
        build_text_response("All figures are present and correctly referenced."),
    ]

    with mock_anthropic_client(*responses):
        result = await agent.run(sample_manuscript, config)

    assert result.checker_name == "figure_table"
    assert len(result.findings) == 0
