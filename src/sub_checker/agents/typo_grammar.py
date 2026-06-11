from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.tools.manuscript_tools import (
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    read_section,
    search_text,
)


class TypoGrammarAgent(BaseCheckerAgent):
    name = "typo_grammar"

    def _default_system_prompt(self) -> str:
        return (
            "You are an academic English proofreader. Your job is to:\n"
            "1. Read through each section of the manuscript carefully\n"
            "2. Identify spelling errors, typos, and grammatical mistakes\n"
            "3. Flag awkward phrasing or non-standard academic English\n"
            "4. Skip the reference list section (reference formatting is handled by another agent)\n"
            "5. Be aware that scientific terms, gene names, chemical names, etc. are NOT typos\n\n"
            "WORKFLOW — follow this exactly:\n"
            "1. Use read_section to read sections one at a time (Abstract, Introduction, "
            "Methods, Results, Discussion, etc.).\n"
            "2. After reading each section, immediately call add_finding for any issues found.\n"
            "3. After you have read ALL sections (excluding References), STOP. Do not re-read.\n"
            "4. If you find no issues in the entire manuscript, simply finish without findings.\n\n"
            "IMPORTANT NOTES:\n"
            "- When checking dates, carefully compare with today's date provided in the "
            "initial message. A date like 'November 2025' is in the PAST if today is 2026. "
            "Only flag dates that are genuinely in the future.\n"
            "- Each section's text is read independently. If you see a word like 'Methods' at "
            "the end of a section, it is likely a standalone heading paragraph that was not "
            "detected as a heading due to Word styling. Do NOT flag it as misplaced text.\n"
            "- Do NOT report naming convention choices (e.g., underscore_names, CamelCase) as "
            "inconsistencies unless there is a genuine mix of different conventions for the same "
            "type of entity within the manuscript.\n\n"
            "Use add_finding for each issue. Include the incorrect text in 'context' "
            "and the suggested correction in 'suggestion'."
        )

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_SEARCH_TEXT,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "search_text":
            return search_text(ms, tool_input["query"])
        return f"Unknown tool: {tool_name}"
