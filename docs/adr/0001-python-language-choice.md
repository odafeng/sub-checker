# 1. Use Python as Implementation Language

## Status

Accepted

## Context

We need to choose a language for building a CLI tool that parses .docx files, calls Claude API, queries PubMed, and performs web searches. The primary consideration is ecosystem maturity for NLP/document processing tasks and Anthropic SDK support.

## Decision

Use Python (>=3.11) with:
- `python-docx` for .docx parsing
- `anthropic` SDK for Claude API (agent tool_use loop)
- `httpx` for async HTTP (PubMed, web fetch)
- `click` for CLI, `rich` for terminal output
- `pydantic` for config validation

## Consequences

- **Positive**: Rich ecosystem for document processing and API integration. Native async support. Anthropic SDK is first-class Python.
- **Positive**: Easy to install via pip, familiar to academic users.
- **Negative**: Slower than compiled languages, but I/O-bound workload makes this irrelevant.
- **Negative**: Requires Python 3.11+ which may not be available on all systems.
