from __future__ import annotations

from sub_checker.agents.base import ADD_FINDING_TOOL, BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.models import Manuscript
from sub_checker.tools.manuscript_tools import (
    TOOL_GET_REFERENCE_LIST,
    TOOL_READ_SECTION,
    TOOL_SEARCH_TEXT,
    count_references,
    extract_citation_numbers,
    get_reference_list,
    read_section,
    search_text,
)


class CitationExistAgent(BaseCheckerAgent):
    name = "citation_exist"

    def _default_system_prompt(self) -> str:
        return (
            "You are a citation completeness reviewer. Your job is to:\n"
            "1. Review the DETERMINISTIC PRE-SCAN results provided in your initial message.\n"
            "   These results were produced by regex and are highly reliable for numbered citations.\n"
            "2. For numbered citations: TRUST the pre-scan. Only report issues if the pre-scan\n"
            "   shows a mismatch (cited number not in reference list, or reference not cited).\n"
            "3. For author-year citations: use tools to read each section and cross-check.\n"
            "4. Check for mismatches in author names or years between citation and reference.\n"
            "5. Read the reference list to verify formatting and detect duplicate entries.\n\n"
            "IMPORTANT: Do NOT override the deterministic pre-scan for numbered citations.\n"
            "The pre-scan has already searched the ENTIRE manuscript text. If it says a number\n"
            "is cited, it IS cited — do not report it as missing.\n\n"
            "Use add_finding to report each issue. severity=error for missing citations, "
            "severity=warning for unreferenced entries."
        )

    def _build_initial_message(self, manuscript: Manuscript, config: Config) -> str:
        """Override to inject deterministic pre-scan results."""
        base_msg = super()._build_initial_message(manuscript, config)

        # Deterministic pre-pass — scan body only, or volume(issue) patterns in
        # the reference list (e.g. "2022;101(27)") show up as phantom citations
        cited_nums = extract_citation_numbers(manuscript.body_text or manuscript.raw_text)
        ref_count = count_references(manuscript.reference_section)
        ref_nums = set(range(1, ref_count + 1)) if ref_count > 0 else set()

        cited_not_in_refs = sorted(cited_nums - ref_nums) if ref_nums else []
        refs_not_cited = sorted(ref_nums - cited_nums) if cited_nums else []

        pre_scan = [
            "\n--- DETERMINISTIC PRE-SCAN (regex, highly reliable) ---",
            f"Citation numbers found in text: {sorted(cited_nums)}",
            f"Total distinct citation numbers: {len(cited_nums)}",
            f"Reference list entries (by line count): {ref_count}",
        ]

        if cited_not_in_refs:
            pre_scan.append(
                f"NEEDS VERIFICATION: numbers found in (...)/[...] but NOT in the "
                f"reference list: {cited_not_in_refs}. These may be real dangling "
                f"citations OR plain data values in parentheses (e.g. '(50)' as a "
                f"measurement, sample size, or percentile). Use search_text on each "
                f"number to see its surrounding context and report ONLY the ones "
                f"that are actually used as citations."
            )
        if refs_not_cited:
            pre_scan.append(
                f"NEEDS VERIFICATION: reference numbers possibly NOT cited in text: "
                f"{refs_not_cited}. CAUTION: the reference count above is a LINE-COUNT "
                f"heuristic — references wrapped across multiple lines inflate it, "
                f"which fabricates phantom 'uncited' numbers at the high end. Use "
                f"get_reference_list to confirm the actual number of entries before "
                f"reporting any of these as uncited."
            )
        if not cited_not_in_refs and not refs_not_cited and cited_nums and ref_nums:
            pre_scan.append("All numbered citations match reference list entries. No mismatches.")

        pre_scan.append("--- END PRE-SCAN ---")
        return base_msg + "\n".join(pre_scan)

    def get_tools(self) -> list[dict]:
        return [
            TOOL_READ_SECTION,
            TOOL_GET_REFERENCE_LIST,
            TOOL_SEARCH_TEXT,
            ADD_FINDING_TOOL,
        ]

    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        ms = self._manuscript
        assert ms is not None
        if tool_name == "read_section":
            return read_section(ms, tool_input["section_name"])
        if tool_name == "get_reference_list":
            return get_reference_list(ms)
        if tool_name == "search_text":
            return search_text(ms, tool_input["query"])
        return f"Unknown tool: {tool_name}"
