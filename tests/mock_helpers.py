"""Helpers for mocking the Anthropic API in agent tests."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch


@dataclass
class MockToolUse:
    type: str = "tool_use"
    id: str = "tool_1"
    name: str = ""
    input: dict = field(default_factory=dict)


@dataclass
class MockTextBlock:
    type: str = "text"
    text: str = ""


@dataclass
class MockUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class MockResponse:
    content: list = field(default_factory=list)
    stop_reason: str = "end_turn"
    usage: MockUsage = field(default_factory=MockUsage)


def build_tool_response(
    tool_calls: list[tuple[str, dict]], tool_id_prefix: str = "tool"
) -> MockResponse:
    """Build a mock response with tool_use blocks."""
    content = []
    for i, (name, inp) in enumerate(tool_calls):
        content.append(MockToolUse(id=f"{tool_id_prefix}_{i}", name=name, input=inp))
    return MockResponse(content=content, stop_reason="tool_use")


def build_text_response(text: str = "Done.") -> MockResponse:
    """Build a mock response with just text (end_turn)."""
    return MockResponse(content=[MockTextBlock(text=text)], stop_reason="end_turn")


def mock_anthropic_client(
    *responses: MockResponse, target: str = "sub_checker.agents.base.anthropic.AsyncAnthropic"
):
    """Create a patched AsyncAnthropic that returns the given responses in sequence.

    Usage:
        with mock_anthropic_client(resp1, resp2, resp3):
            result = await agent.run(manuscript, config)
    """
    mock_create = AsyncMock(side_effect=list(responses))
    mock_client_instance = MagicMock()
    mock_client_instance.messages.create = mock_create
    # Support `async with AsyncAnthropic() as client:` — __aenter__ must yield
    # the configured instance, not a fresh MagicMock.
    mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
    mock_client_instance.__aexit__ = AsyncMock(return_value=False)

    return patch(target, return_value=mock_client_instance)
