from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.tools.manuscript_tools import (
    TOOL_READ_PARAGRAPH,
    TOOL_READ_SECTION,
    read_paragraph,
    read_section,
)


class LogicAgent(BaseCheckerAgent):
    name = "logic"

    def _default_system_prompt(self) -> str:
        return (
            "You are an academic peer reviewer focused on logical consistency. Your job is to:\n"
            "1. Read through the manuscript section by section\n"
            "2. Identify logical issues:\n"
            "   - Contradictory statements between sections\n"
            "   - Unsupported causal claims\n"
            "   - Conclusions that go beyond what the data supports\n"
            "   - Methods that don't match the reported results\n"
            "   - Inconsistent use of terminology\n"
            "   - Missing logical connections between arguments\n"
            "3. Focus on scientific reasoning, not grammar or formatting\n\n"
            "Use add_finding for each logic issue. severity=error for contradictions, "
            "severity=warning for questionable claims."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_READ_PARAGRAPH,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "read_paragraph":
            return read_paragraph(ms, tool_input["index"])
        return f"Unknown tool: {tool_name}"
