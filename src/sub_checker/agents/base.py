from __future__ import annotations

import copy
import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any, cast

import anthropic
from anthropic.types import MessageParam, ToolParam

from sub_checker.config import Config
from sub_checker.logging_config import _DEFAULT_COT_DIR, AgentCOTLogger
from sub_checker.models import (
    CheckerResult,
    Finding,
    Manuscript,
    Severity,
    TokenUsage,
)
from sub_checker.sizing import TRUNCATION_MARKER

logger = logging.getLogger("sub_checker.agents")

# Safety cap on the agentic loop: prevents runaway token spend if the model
# never reaches end_turn.
MAX_ITERATIONS = 30


def supports_adaptive_thinking(model: str) -> bool:
    """Adaptive thinking is available on Opus 4.6+ / Sonnet 4.6 / Fable 5."""
    return any(
        marker in model for marker in ("opus-4-6", "opus-4-7", "opus-4-8", "sonnet-4-6", "fable")
    )


def set_message_cache_breakpoint(messages: list[MessageParam]) -> None:
    """Mark the last content block of the last message with cache_control.

    Moves the single message-level cache breakpoint forward each iteration so
    the entire conversation prefix is served from the prompt cache. Combined
    with the system + tools breakpoints this stays within the 4-breakpoint
    API limit.
    """
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    block.pop("cache_control", None)

    last_content = messages[-1].get("content")
    if isinstance(last_content, list) and last_content and isinstance(last_content[-1], dict):
        last_block = cast("dict[str, Any]", last_content[-1])
        last_block["cache_control"] = {"type": "ephemeral"}


class BaseCheckerAgent(ABC):
    """Base class for all checker agents.

    Each agent runs an agentic loop:
    1. Send system prompt + tools + initial message to Claude
    2. If Claude returns tool_use → execute tool → feed result back → repeat
    3. If Claude returns text (done) → collect all add_finding calls → return CheckerResult
    """

    name: str = "base"
    # Reasoning depth / token budget. Mechanical checkers (pattern matching,
    # cross-referencing) override this down to save output tokens; judgment-
    # heavy checkers keep "high". GA on Sonnet 4.6 and Opus 4.6+.
    effort: str = "high"

    def __init__(self, model: str = "claude-opus-4-8"):
        self.model = model
        self._findings: list[Finding] = []
        self._token_usage = TokenUsage()
        self._manuscript: Manuscript | None = None
        self._tool_truncation_noted = False

    @cached_property
    def system_prompt(self) -> str:
        prompt_path = Path(__file__).parent / "prompts" / f"{self.name}.txt"
        if prompt_path.exists():
            return prompt_path.read_text()
        return self._default_system_prompt()

    @abstractmethod
    def _default_system_prompt(self) -> str:
        """Fallback system prompt if no .txt file exists."""
        ...

    @abstractmethod
    def get_tools(self) -> list[dict]:
        """Return tool definitions for this agent."""
        ...

    @abstractmethod
    async def handle_tool_call(self, tool_name: str, tool_input: dict) -> str:
        """Execute a tool and return the result as a string."""
        ...

    def _build_initial_message(self, manuscript: Manuscript, config: Config) -> str:
        """Build the initial user message with task context."""
        today = datetime.now(UTC).strftime("%Y-%m-%d")
        parts = [
            f"Today's date: {today}",
            f'Please check the following manuscript: "{manuscript.title}"',
        ]
        if config.journal:
            parts.append(f"Target journal: {config.journal}")
        else:
            parts.append(
                "Target journal: NOT SPECIFIED. "
                "Do NOT assume any journal-specific requirements (formatting, "
                "citation style, word limits). Only check internal consistency "
                "within the manuscript itself."
            )
        parts.append(
            f"The manuscript has {len(manuscript.sections)} sections "
            f"and {len(manuscript.paragraphs)} paragraphs."
        )
        parts.append("Use the provided tools to read the manuscript and report any findings.")
        parts.append(
            "When calling add_finding, ALWAYS set claim_type (and claimed_date / "
            "ref_number where applicable) — the validation harness uses these "
            "fields to fact-check findings deterministically."
        )
        if config.output_lang == "zh-TW":
            parts.append(
                "\nIMPORTANT: Write ALL your findings (message, suggestion) in Traditional Chinese (繁體中文). "
                "The manuscript itself is in English, but your output in add_finding must be in 繁體中文. "
                "Example: message='引用 [15] 在文中被引用但參考文獻列表中缺失', "
                "suggestion='請在參考文獻列表中新增 [15] 或修正引用編號'"
            )
        return "\n".join(parts)

    def _handle_add_finding(self, tool_input: dict) -> str:
        """Process an add_finding tool call."""
        severity_str = tool_input.get("severity", "warning").upper()
        try:
            severity = Severity[severity_str]
        except KeyError:
            severity = Severity.WARNING

        ref_number = tool_input.get("ref_number")
        if not isinstance(ref_number, int):
            ref_number = None

        finding = Finding(
            checker=self.name,
            severity=severity,
            message=tool_input.get("message", ""),
            location=tool_input.get("location"),
            suggestion=tool_input.get("suggestion"),
            context=tool_input.get("context"),
            claim_type=tool_input.get("claim_type"),
            claimed_date=tool_input.get("claimed_date"),
            ref_number=ref_number,
        )
        self._findings.append(finding)
        return f"Finding recorded: [{severity.value}] {finding.message}"

    def _note_incomplete(self, message: str) -> None:
        """Record that this check is incomplete.

        validation_status="confirmed" keeps the note out of the harness/
        reviewer (which could otherwise filter it as "not a manuscript
        issue"), so the user always sees that coverage was partial.
        """
        self._findings.append(
            Finding(
                checker=self.name,
                severity=Severity.INFO,
                message=message,
                claim_type="other",
                validation_status="confirmed",
                validation_note="[harness] incomplete-run notice, not reviewed",
            )
        )

    async def run(self, manuscript: Manuscript, config: Config) -> CheckerResult:
        """Execute the agent loop with full logging."""
        self._manuscript = manuscript
        self._findings = []
        self._token_usage = TokenUsage()
        self._tool_truncation_noted = False
        start = time.monotonic()

        run_id = uuid.uuid4().hex[:8]
        if config.cot_dir == "disabled":
            cot_dir = None  # explicitly disable COT file output
        elif config.cot_dir:
            cot_dir = Path(config.cot_dir)  # custom directory
        else:
            cot_dir = _DEFAULT_COT_DIR  # None in config → use default
        cot = AgentCOTLogger(
            agent_name=self.name,
            run_id=run_id,
            cot_dir=cot_dir,
        )
        logger.info("Starting agent '%s' (run_id=%s)", self.name, run_id)

        # Deep-copy: tool definitions are shared module constants and we add
        # a cache_control marker to the last one (caches system + tools prefix).
        tools = cast(list[ToolParam], copy.deepcopy(self.get_tools()))
        if tools:
            tools[-1]["cache_control"] = {"type": "ephemeral"}  # type: ignore[typeddict-unknown-key]
        system_blocks = [
            {
                "type": "text",
                "text": self.system_prompt,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        messages = cast(
            list[MessageParam],
            [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": self._build_initial_message(manuscript, config),
                        }
                    ],
                }
            ],
        )

        iteration = 0
        try:
            async with anthropic.AsyncAnthropic() as client:
                while True:
                    iteration += 1
                    if iteration > MAX_ITERATIONS:
                        logger.warning(
                            "[%s] Hit max iterations (%d), stopping agent loop",
                            self.name,
                            MAX_ITERATIONS,
                        )
                        self._note_incomplete(
                            f"Check stopped after reaching the {MAX_ITERATIONS}-iteration "
                            "safety cap — some items may not have been checked."
                        )
                        break
                    logger.debug("[%s] Iteration %d: sending API request", self.name, iteration)
                    cot.log_request(messages, tools)
                    set_message_cache_breakpoint(messages)

                    extra: dict[str, Any] = {}
                    if supports_adaptive_thinking(self.model):
                        # Adaptive thinking + per-checker effort: low effort
                        # keeps thinking minimal (and avoids reasoning leaking
                        # into the visible response on Opus 4.8).
                        extra["thinking"] = {"type": "adaptive"}
                        extra["output_config"] = {"effort": self.effort}
                    response = await client.messages.create(
                        model=self.model,
                        max_tokens=16000,
                        system=system_blocks,  # type: ignore[arg-type]
                        tools=tools,
                        messages=messages,
                        **extra,
                    )

                    self._token_usage.input_tokens += response.usage.input_tokens
                    self._token_usage.output_tokens += response.usage.output_tokens
                    self._token_usage.cache_creation_input_tokens += (
                        response.usage.cache_creation_input_tokens or 0
                    )
                    self._token_usage.cache_read_input_tokens += (
                        response.usage.cache_read_input_tokens or 0
                    )
                    cot.log_response(str(response.stop_reason), response.content)

                    if response.stop_reason == "end_turn":
                        logger.debug("[%s] Agent finished (end_turn)", self.name)
                        break

                    truncated = response.stop_reason == "max_tokens"
                    content_blocks = list(response.content)
                    if truncated:
                        logger.warning(
                            "[%s] Response truncated at max_tokens on iteration %d",
                            self.name,
                            iteration,
                        )
                        # A trailing tool_use may carry incomplete input —
                        # never execute a half-formed call (e.g. a cut-off
                        # add_finding would record a garbage finding).
                        if content_blocks:
                            last = content_blocks[-1]
                            if last.type == "tool_use":
                                content_blocks.pop()
                                logger.warning(
                                    "[%s] Dropped truncated tool_use '%s'", self.name, last.name
                                )

                    # Process tool calls
                    tool_results = []
                    for block in content_blocks:
                        if block.type == "tool_use":
                            logger.debug(
                                "[%s] Tool call: %s(%s)", self.name, block.name, block.input
                            )

                            if block.name == "add_finding":
                                result = self._handle_add_finding(block.input)
                                inp = block.input
                                cot.log_finding(
                                    str(inp.get("severity", "warning")),
                                    str(inp.get("message", "")),
                                )
                            else:
                                try:
                                    result = await self.handle_tool_call(block.name, block.input)
                                except Exception as e:
                                    result = f"Tool error: {e}"
                                    logger.error(
                                        "[%s] Tool '%s' failed: %s",
                                        self.name,
                                        block.name,
                                        e,
                                        exc_info=True,
                                    )
                                    cot.log_error(f"Tool '{block.name}' failed: {e}", e)

                            if TRUNCATION_MARKER in result and not self._tool_truncation_noted:
                                self._note_incomplete(
                                    "Check coverage is partial: at least one manuscript tool "
                                    "result exceeded the safe context budget and was truncated."
                                )
                                self._tool_truncation_noted = True

                            cot.log_tool_result(block.name, block.id, result)
                            tool_results.append(
                                {"type": "tool_result", "tool_use_id": block.id, "content": result}
                            )

                    if not tool_results:
                        if truncated:
                            self._note_incomplete(
                                "Check may be incomplete: the model response was "
                                "truncated at the token limit before any tool call."
                            )
                        logger.debug("[%s] No tool results, ending loop", self.name)
                        break

                    messages.append(
                        cast(MessageParam, {"role": "assistant", "content": content_blocks})
                    )
                    messages.append(cast(MessageParam, {"role": "user", "content": tool_results}))

        except anthropic.APIError as e:
            # Keep findings already collected (paid for) instead of discarding
            # the whole run; flag the result as incomplete.
            logger.error("[%s] API error, returning partial result: %s", self.name, e)
            cot.log_error(f"API error (partial result): {e}", e)
            self._note_incomplete(
                f"Check incomplete: the API failed after {iteration} iterations ({e}). "
                f"{len(self._findings)} finding(s) collected before the failure are kept."
            )
        except Exception as e:
            logger.error("[%s] Agent failed: %s", self.name, e, exc_info=True)
            cot.log_error(f"Agent failed: {e}", e)
            raise
        finally:
            elapsed = time.monotonic() - start
            cot_path = cot.save()
            logger.info(
                "[%s] Completed in %.1fs (%d findings, %d iterations). COT: %s",
                self.name,
                elapsed,
                len(self._findings),
                iteration,
                cot_path,
            )

        return CheckerResult(
            checker_name=self.name,
            findings=list(self._findings),
            elapsed_seconds=elapsed,
            token_usage=self._token_usage,
            cot_entries=cot.entries,
            model=self.model,
        )


# Shared tool definition for add_finding (all agents use this)
ADD_FINDING_TOOL = {
    "name": "add_finding",
    "description": "Report a finding/issue found in the manuscript.",
    "input_schema": {
        "type": "object",
        "properties": {
            "severity": {
                "type": "string",
                "enum": ["error", "warning", "info"],
                "description": "Severity: error (must fix), warning (should review), info (suggestion)",
            },
            "message": {
                "type": "string",
                "description": "Description of the issue found",
            },
            "location": {
                "type": "string",
                "description": "Where in the manuscript (e.g. 'Section: Methods, Paragraph 5')",
            },
            "suggestion": {
                "type": "string",
                "description": "How to fix the issue",
            },
            "context": {
                "type": "string",
                "description": "Surrounding text snippet for context",
            },
            "claim_type": {
                "type": "string",
                "enum": [
                    "future_date",
                    "uncited_reference",
                    "missing_reference",
                    "inconsistency",
                    "other",
                ],
                "description": (
                    "Machine-checkable claim category. Use 'future_date' when the finding "
                    "claims a date is in the future, 'uncited_reference' when a reference "
                    "list entry is claimed to never be cited in the text, "
                    "'missing_reference' when a citation number is claimed to be absent "
                    "from the reference list, 'inconsistency' for format/style "
                    "inconsistency claims, 'other' otherwise. ALWAYS set this field — it "
                    "lets the validation harness fact-check the finding deterministically."
                ),
            },
            "claimed_date": {
                "type": "string",
                "description": (
                    "For claim_type='future_date': the date the claim is about, "
                    "as 'YYYY' or 'YYYY-MM' (e.g. '2025-11')"
                ),
            },
            "ref_number": {
                "type": "integer",
                "description": (
                    "For citation-related claims: the reference/citation number "
                    "the finding concerns (e.g. 23 for reference [23])"
                ),
            },
        },
        "required": ["severity", "message"],
    },
}
