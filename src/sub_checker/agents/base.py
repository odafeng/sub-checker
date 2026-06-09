from __future__ import annotations

import logging
import time
import uuid
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

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

logger = logging.getLogger("sub_checker.agents")


class BaseCheckerAgent(ABC):
    """Base class for all checker agents.

    Each agent runs an agentic loop:
    1. Send system prompt + tools + initial message to Claude
    2. If Claude returns tool_use → execute tool → feed result back → repeat
    3. If Claude returns text (done) → collect all add_finding calls → return CheckerResult
    """

    name: str = "base"

    def __init__(self, model: str = "claude-sonnet-4-20250514"):
        self.model = model
        self._findings: list[Finding] = []
        self._token_usage = TokenUsage()

    @property
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
        parts.append(
            f"The manuscript has {len(manuscript.sections)} sections "
            f"and {len(manuscript.paragraphs)} paragraphs."
        )
        parts.append("Use the provided tools to read the manuscript and report any findings.")
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

        finding = Finding(
            checker=self.name,
            severity=severity,
            message=tool_input.get("message", ""),
            location=tool_input.get("location"),
            suggestion=tool_input.get("suggestion"),
            context=tool_input.get("context"),
        )
        self._findings.append(finding)
        return f"Finding recorded: [{severity.value}] {finding.message}"

    async def run(self, manuscript: Manuscript, config: Config) -> CheckerResult:
        """Execute the agent loop with full logging."""
        self._findings = []
        self._token_usage = TokenUsage()
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

        client = anthropic.AsyncAnthropic()
        tools = cast(list[ToolParam], self.get_tools())
        messages = cast(
            list[MessageParam],
            [{"role": "user", "content": self._build_initial_message(manuscript, config)}],
        )

        iteration = 0
        try:
            while True:
                iteration += 1
                logger.debug("[%s] Iteration %d: sending API request", self.name, iteration)
                cot.log_request(messages, tools)

                response = await client.messages.create(
                    model=self.model,
                    max_tokens=4096,
                    system=self.system_prompt,
                    tools=tools,
                    messages=messages,
                )

                self._token_usage.input_tokens += response.usage.input_tokens
                self._token_usage.output_tokens += response.usage.output_tokens
                cot.log_response(str(response.stop_reason), response.content)

                if response.stop_reason == "end_turn":
                    logger.debug("[%s] Agent finished (end_turn)", self.name)
                    break

                # Process tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logger.debug("[%s] Tool call: %s(%s)", self.name, block.name, block.input)

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

                        cot.log_tool_result(block.name, block.id, result)
                        tool_results.append(
                            {"type": "tool_result", "tool_use_id": block.id, "content": result}
                        )

                if not tool_results:
                    logger.debug("[%s] No tool results, ending loop", self.name)
                    break

                messages.append(
                    cast(MessageParam, {"role": "assistant", "content": response.content})
                )
                messages.append(cast(MessageParam, {"role": "user", "content": tool_results}))

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
        },
        "required": ["severity", "message"],
    },
}
