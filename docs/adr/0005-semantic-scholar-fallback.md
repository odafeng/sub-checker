# 5. Semantic Scholar as PubMed Fallback

## Status

Accepted

## Context

The citation-claim verification agent originally only searched PubMed. This meant papers not indexed in PubMed (CS, engineering, social sciences, preprints) could not be verified, producing false NOT_FOUND results. The user's manuscript referenced a 2024 paper (Lambert et al.) that PubMed hadn't indexed yet.

## Decision

Add Semantic Scholar (S2) API as a fallback:
1. `search_literature()` tries PubMed first (NCBI E-utilities)
2. If PubMed returns zero results, falls back to S2 Graph API (`/paper/search`)
3. `get_abstract()` tries PubMed for numeric PMIDs, then S2 for any identifier (S2 ID, DOI, PMID)
4. S2 client has its own caching layer (search results + paper details)

The tool exposed to the agent is renamed from `search_pubmed` to `search_literature` to reflect the broader coverage.

## Consequences

- **Positive**: Much broader coverage — S2 indexes 200M+ papers across all fields.
- **Positive**: S2 API is free (no API key required, though rate-limited).
- **Positive**: Accepts DOI and PMID as lookup keys, not just S2 paper IDs.
- **Negative**: S2 rate limits are stricter than PubMed (100 req/5min without key). Mitigated by semaphore + caching.
- **Negative**: S2 abstract quality can vary (some papers have no abstract).
- **Negative**: Two HTTP clients to manage (PubMedClient + SemanticScholarClient).
