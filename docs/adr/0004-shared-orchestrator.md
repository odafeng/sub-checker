# 4. Shared Orchestrator for CLI and API

## Status

Accepted

## Context

The CLI pipeline (`pipeline.py`) and FastAPI WebSocket handler (`api.py`) both needed to: create agents, group them into phases, run them in parallel, calculate cost, and build a Report. This logic was duplicated, creating a risk of divergence — a bug fix or phase reordering in one path could be missed in the other.

## Decision

Extract a shared `orchestrator.py` module as the single source of truth for:
- `create_agents(config)` — agent instantiation
- `filter_agents(agents, only, skip)` — filtering by name
- `PHASE_GROUPS` — phase definitions (which agents run in parallel)
- `run_agent_safe(agent, manuscript, config, on_progress)` — error-handling wrapper
- `run_all_phases(agents, manuscript, config, on_progress)` — phased execution
- `build_report(results, manuscript_path, journal)` — cost calculation + Report construction

Both `pipeline.py` (CLI with Rich progress) and `api.py` (WebSocket with JSON progress) become thin wrappers that provide their own `on_progress` callback.

## Consequences

- **Positive**: Phase logic, cost formula, and agent creation defined once. Changes propagate to both CLI and API automatically.
- **Positive**: The `AgentCallback` type makes progress reporting pluggable — easy to add new frontends.
- **Positive**: Easier to test orchestration logic in isolation.
- **Negative**: One more module to understand. But it's the obvious place to look for "how does a check run?"
