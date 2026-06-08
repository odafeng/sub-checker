# 2. Agent-per-Checker Architecture

## Status

Accepted

## Context

We need to check academic manuscripts for multiple types of issues (typos, logic, citations, figures, journal compliance). Initially considered regex-based checkers, but academic text has too many format variations for reliable regex matching.

## Decision

Each checker is implemented as a Claude agent using the Anthropic SDK's tool_use pattern:
- Each agent has a specialized system prompt defining its role
- Each agent has access to a curated set of tools (read_section, list_figures, web_search, etc.)
- The agent autonomously decides which tools to call and when
- Findings are reported via a structured `add_finding` tool
- A manual agentic loop (while True → messages.create → handle tool_use) gives full control

## Consequences

- **Positive**: Much more robust than regex — LLM understands context, handles variations naturally.
- **Positive**: Each agent is independently testable (mock the API, verify tool dispatch).
- **Positive**: Tool-based architecture gives observability (every tool call is logged).
- **Positive**: `add_finding` tool enforces structured output without parsing free text.
- **Negative**: Requires API key and incurs per-check cost (~$0.80-1.50 per manuscript).
- **Negative**: Slower than offline regex — each agent needs multiple API round-trips.
- **Negative**: Non-deterministic — same manuscript may produce slightly different findings across runs.
