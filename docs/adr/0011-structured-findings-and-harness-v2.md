# 11. Structured findings, agentic reviewer, and harness v2

Date: 2026-06-10

## Status

Accepted

## Context

The original harness (ADR-0010) cut false positives dramatically, but an
architecture review identified five structural weaknesses:

1. **Deterministic checks parsed LLM prose.** `validate_date_claims` looked
   for month names within 30 characters of "future/未來" in the finding
   message. Any rephrasing broke validation, and bilingual output doubled the
   pattern surface.
2. **The reviewer judged findings from a truncated preview.** It received the
   first few thousand characters of the manuscript, so verdicts about later
   sections were guesses — yet it had the power to delete findings.
3. **Heuristic-based filters could systematically delete real findings.**
   `validate_citation_numbers` trusted a line-count estimate of the reference
   list; a wrapped reference entry would silently filter true positives.
4. **Phase barriers added latency without expressing dependencies.** No data
   flows between checkers; the 3-phase grouping was de-facto concurrency
   control, and a slow Phase-1 checker blocked unrelated Phase-2 checkers.
5. **Every checker ran on Opus.** Mechanical checks (typo, figure/table,
   citation format/existence) don't need Opus-level reasoning; they dominated
   the ~$8-12 per-run cost.

## Decision

**Structured findings.** `add_finding` gains optional machine-checkable
fields: `claim_type` (future_date / uncited_reference / missing_reference /
inconsistency / other), `claimed_date` (YYYY or YYYY-MM), and `ref_number`.
Deterministic checks validate these fields first and fall back to prose
parsing only for findings without them.

**Fail-safe deterministic actions.** Checks backed by exact data (regex scan
of the actual manuscript text) may `filter`. Checks backed by heuristics
(reference count by line) may only `downgrade`; the reviewer makes the final
call. Downgrades record `original_severity` so a reviewer confirmation
restores the finding's true severity.

**Agentic reviewer.** The reviewer now has read_section / search_text /
get_reference_list tools and is instructed to verify against the manuscript
before filtering anything. Verdicts are returned via a `submit_verdicts` tool
call (schema-enforced) with a text-JSON fallback. Findings are reviewed in
batches of 25 so one bad response can't drop all verdicts.

**Bounded concurrency replaces phases.** All checkers run under a global
`asyncio.Semaphore` (`max_concurrent_agents`, default 3), scheduled light
checkers first and citation_claim last. Post-validation phases renumber to:
Phase 1 execution, Phase 2 deterministic, Phase 3 reviewer.

**Per-checker models.** `Config.models` maps checker → model with defaults
running the four mechanical checkers on Sonnet; `logic`, `citation_claim`,
`journal_guidelines`, and the reviewer stay on the global `model` (Opus).
`reviewer_model` allows overriding the reviewer separately. Cost accounting
prices each result with the model that actually produced it.

## Consequences

**Positive:**

- Deterministic validation is language- and phrasing-independent for any
  finding that carries structured fields.
- The reviewer verifies evidence instead of guessing from a preview; its
  filter verdicts are grounded in tool-read manuscript text.
- Heuristic checks can no longer hard-delete true findings.
- Wall-clock time improves: no barrier waits; concurrency is explicit.
- Default cost drops roughly 40-60% (four checkers move from Opus to Sonnet
  pricing) without touching the judgment-heavy paths.

**Negative:**

- Structured fields rely on agents filling them; the prose fallback remains
  as a safety net and must be kept in sync with output-language patterns.
- The agentic reviewer costs more tokens than the single-shot version
  (tool rounds), partially offset by prompt caching and Sonnet checkers.
- Mixed-model runs make "which model produced this?" per-finding metadata
  important; the JSON report now carries `model` per checker result.
