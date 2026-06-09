# 10. Plan-Execute-Verify harness architecture

Date: 2026-06-10

## Status

Accepted

## Context

After testing with real manuscripts, the 7 checker agents produced significant false positives:

- Incorrect date arithmetic ("November 2025 is a future date" when today is 2026)
- Citation existence errors (references 23-29 falsely reported as uncited)
- Self-contradictory findings ("X uses underscores, but Y also uses underscores")
- Assumed citation format (Vancouver) when no journal was specified

Prompt patching (adding rules to system prompts) proved fragile — each new edge case required a new rule, prompts grew unwieldy, and models didn't reliably follow all rules.

Industry patterns (Agent Harness Engineering, 2026) advocate a Plan-Execute-Verify loop where agent outputs pass through deterministic and LLM-based validation before reaching users.

## Decision

Implement a 5-phase pipeline with post-validation harness:

**Phase 1-3: Agent Execution** (existing 7 agents in 3 parallel groups)

**Phase 4: Deterministic Post-Validation** (zero cost, <1ms)
- Date math: verify any "future date" claims against actual current date
- Citation cross-check: regex-extracted citation numbers vs agent conclusions
- Self-consistency: detect findings whose evidence contradicts their own claim

**Phase 5: Reviewer Agent** (Opus 4.8, ~$0.50 per run)
- Independent agent reviews ALL findings against manuscript context
- For each finding: confirm, downgrade (to info), or filter (remove)
- Adds confidence score (0.0-1.0) to each surviving finding
- Trained on common false positive patterns

Additionally, pre-execution harnesses were added:
- **Deterministic pre-pass**: regex citation extraction injected into citation_exist agent context
- **Multi-source verification**: PubMed + Semantic Scholar + Crossref queried in parallel, cross-validated, results injected into citation_claim agent context

## Consequences

**Positive:**

- False positives dropped from ~7 per manuscript to 0 in testing.
- Findings count dropped from 79 (noisy) to 33 (actionable) on the same manuscript.
- New true findings emerged (Pearson vs Spearman, CT vs MRI contradictions) that were previously missed — agents spend tokens on real analysis instead of chasing false leads.
- Confidence scores give users a trust signal for each finding.
- Deterministic checks are free and instant — no API cost.
- Architecture is model-agnostic: upgrading to a better model improves all phases.

**Negative:**

- Reviewer agent adds ~$0.50 and ~30s per run (one extra Opus call).
- Total pipeline time increases by ~30-60s (reviewer + multi-source verification).
- Multi-source verifier hits rate limits on PubMed/S2/Crossref; requires batching (3 refs at a time) and retry logic, adding complexity.
- Reviewer agent itself could have false negatives (incorrectly filtering a valid finding). Deterministic checks mitigate this for measurable claims.
- The harness adds ~500 lines of code to maintain (deterministic.py, reviewer.py, citation_verifier.py, crossref.py).
