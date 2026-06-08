# 7. Injectable COT Logging with Privacy Controls

## Status

Accepted

## Context

Agent chain-of-thought (COT) logs record every tool call and response, which is valuable for debugging and auditing. However:
1. COT logs may contain manuscript excerpts (unpublished research data).
2. Default write to `~/.sub-checker/cot/` caused test pollution — tests wrote to the user's home directory.
3. No way to disable COT logging for privacy-sensitive environments.

## Decision

Make COT logging injectable and configurable:
- `AgentCOTLogger(cot_dir=...)` accepts a custom directory or `None` to disable file output.
- `Config.cot_dir` field: `None` = default (`~/.sub-checker/cot`), `"disabled"` = no file writes, or a custom path.
- `AgentCOTLogger.entries` property provides read-only access to in-memory entries for testing.
- Tests use `Config(cot_dir="disabled")` — zero filesystem side effects.
- Module docstring documents that COT logs may contain manuscript content.

## Consequences

- **Positive**: Tests are fully isolated — no writes to `~/.sub-checker/`.
- **Positive**: Users can disable COT for privacy or set a custom path.
- **Positive**: COT entries still available in memory for programmatic access.
- **Negative**: Slightly more complex `AgentCOTLogger` constructor (3 states: default/custom/disabled).
