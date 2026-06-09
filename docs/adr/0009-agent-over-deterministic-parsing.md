# 9. Prefer agent judgment over deterministic parsing for document structure

Date: 2026-06-09

## Status

Accepted

## Context

The manuscript checker parses `.docx` files into a structured `Manuscript` model (title, sections, paragraphs, references). Early versions relied heavily on deterministic heuristics — matching Word heading styles, inferring title from `sections[0].heading`, detecting abstracts by section name.

Real-world manuscripts use diverse Word styles: custom styles like `JenniRefHeader` for references, `Normal` for abstracts, auto-numbered lists for reference numbering, and titles placed as plain text before any heading. These variations caused cascading false positives:

- Title detected as "Introduction" (first heading) instead of the actual title
- Abstract reported as missing (not a heading-styled paragraph)
- Methods reported as empty (content in sub-sections only)
- Reference numbering reported as missing (Word auto-numbering stripped during extraction)
- Superscript/bracket format mixing hallucinated (formatting lost in plain text)

In one test run, 7 out of 49 findings were factually wrong — all traceable to parser misinterpretation that agents blindly trusted.

## Decision

Minimize deterministic structural inference. Instead, provide agents with raw data and let them judge structure themselves:

1. **`header_text` field**: Parser collects all text before the first heading (title, authors, affiliations, abstract) and exposes it as raw text.
2. **`read_manuscript_header` tool**: Agents can inspect the raw document start to determine the true title and author information, regardless of Word styling.
3. **Tool-level caveats**: `get_reference_list` output includes a note that Word auto-numbering may be stripped. `citation_format` prompt explicitly warns about formatting loss.
4. **Agent prompts**: Instruct agents to verify structure themselves (e.g., check sub-sections before claiming a section is empty, search before claiming content is missing).
5. **Text-match heading detection**: For critical sections (References, Abstract), detect by paragraph text content rather than requiring specific Word heading styles.

The parser still provides structure when it can — but agents are instructed not to trust it blindly and to cross-check with raw data.

## Consequences

**Positive:**

- Eliminated all 7 confirmed false positives from the test manuscript in one iteration.
- Works with arbitrary Word styles, templates, and formatting conventions.
- New findings emerged (e.g., p-value inconsistency between Abstract and Results) because agents spent tokens on real analysis instead of chasing parser artifacts.
- Architecture naturally improves as models get smarter — agent judgment scales with model capability.

**Negative:**

- Higher token usage per run: agents now read raw header text and cross-check structure, adding ~5-10% to input tokens.
- Agent behavior is non-deterministic — the same manuscript may produce slightly different findings across runs.
- Debugging is harder: when a finding is wrong, the root cause could be in the prompt, the model's reasoning, or the tool output. COT viewer in HTML report partially mitigates this.
- Risk of under-reporting: an agent might miss a genuinely missing section if it over-trusts the raw text. Deterministic checks would catch this consistently.
