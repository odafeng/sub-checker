# 3. PubMed + LLM Hybrid Citation Verification

## Status

Accepted

## Context

We need to verify whether cited references actually support the claims made in the manuscript. This requires both finding the cited paper and understanding its content in relation to the claim.

## Decision

Use a two-stage hybrid approach:
1. **PubMed API** (NCBI E-utilities): Search by author + year + keywords to find the cited paper and retrieve its abstract.
2. **Claude API**: Given the claim from the manuscript and the abstract from PubMed, judge whether the abstract supports, contradicts, or provides insufficient evidence for the claim.

## Consequences

- **Positive**: PubMed provides authoritative metadata and abstracts — no hallucination risk for factual lookups.
- **Positive**: LLM excels at semantic comparison (claim vs abstract) which is impossible with keyword matching.
- **Positive**: Rate limiting and caching prevent PubMed API abuse.
- **Negative**: Only works for papers indexed in PubMed (primarily biomedical). Papers from other fields may not be found.
- **Negative**: PubMed search by author+year is imprecise — may return wrong papers for common names.
- **Negative**: Abstract alone may not contain enough detail to verify specific claims (e.g., statistical values).
