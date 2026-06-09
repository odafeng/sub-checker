# 8. Claude Code automated PR review

Date: 2026-06-09

## Status

Accepted

## Context

The project has lint (ruff), type-check (pyright), and test jobs in CI, but no automated code review that examines semantics, logic, or design quality. Manual review is the bottleneck for a solo-maintainer project — PRs can sit unreviewed, and self-review is prone to blind spots.

Options considered:

1. **GitHub Copilot code review** — requires GitHub Copilot Enterprise subscription.
2. **anthropics/claude-code-action** — official Anthropic GitHub Action; uses the same Claude model the project already depends on; pay-per-use via existing API key.
3. **Custom script calling Claude API** — full control, but significant maintenance overhead for prompt engineering, diff parsing, and comment posting.

## Decision

Use `anthropics/claude-code-action@v1` in a dedicated `code-review.yml` workflow. It triggers on `pull_request` (opened/synchronize) and `issue_comment` (for `@claude` follow-up questions). The workflow requires only `ANTHROPIC_API_KEY` as a repository secret.

## Consequences

**Positive:**

- Every PR gets an immediate semantic review (logic errors, security issues, style) alongside existing lint/test checks.
- Reviewers can ask follow-up questions via `@claude` in PR comments.
- Zero additional tooling to maintain — the Action handles diff extraction, prompt construction, and comment posting.
- Uses the same Anthropic API key and billing the project already has.

**Negative:**

- Adds API cost per PR (~$0.50–2.00 depending on diff size). Could accumulate if PRs are frequent or large.
- Review quality depends on the model's current capabilities — may produce false positives or miss domain-specific issues.
- Repository secret (`ANTHROPIC_API_KEY`) must be managed; if leaked, it exposes billing.
- The Action is a third-party dependency (even if from Anthropic) — breaking changes in major versions could disrupt the workflow.
