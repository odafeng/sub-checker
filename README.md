# sub-checker

[![PyPI version](https://img.shields.io/pypi/v/sub-checker.svg)](https://pypi.org/project/sub-checker/)
[![Python versions](https://img.shields.io/pypi/pyversions/sub-checker.svg)](https://pypi.org/project/sub-checker/)
[![CI](https://github.com/odafeng/sub-checker/actions/workflows/ci.yml/badge.svg)](https://github.com/odafeng/sub-checker/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/pypi/l/sub-checker.svg)](https://github.com/odafeng/sub-checker/blob/main/LICENSE)

[繁體中文](README.zh-TW.md) | English

Pre-submission manuscript checker powered by Claude agents with a Plan-Execute-Verify harness. Each check is performed by a specialized AI agent, then validated by deterministic checks and a reviewer agent to eliminate false positives.

## What it checks

| Agent | What it does |
|-------|-------------|
| **typo_grammar** | Spelling, grammar, awkward phrasing (skips reference list) |
| **figure_table** | Figure/table references exist, numbering is sequential, files present |
| **citation_exist** | In-text citations match the reference list (deterministic pre-scan + agent) |
| **citation_format** | Reference list follows target journal's citation style (APA, Vancouver, AMA, etc.) |
| **journal_guidelines** | Word count, required sections, abstract format, required statements (COI, ethics, data availability) |
| **logic** | Contradictions, unsupported claims, methods-results mismatches |
| **citation_claim** | Multi-source verification (PubMed + Semantic Scholar + Crossref), then verifies claims against abstracts |

## Install

```bash
pip install sub-checker
```

## Setup

You need an Anthropic API key:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

Or create a `.env` file in your working directory:

```
ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

### CLI

```bash
# Full check with target journal
sub-check paper.docx -j "The Lancet"

# Chinese report output
sub-check paper.docx -j "Nature Medicine" --lang zh-TW

# Only run specific checkers (cheaper & faster)
sub-check paper.docx --only figure,citation

# Skip expensive checkers
sub-check paper.docx --skip claim,logic

# Output as styled HTML report (includes COT viewer + confidence scores)
sub-check paper.docx -o html --output-file report.html

# Output as JSON (for programmatic use)
sub-check paper.docx -o json --output-file report.json

# Dry run (just parse, no agents)
sub-check paper.docx --dry-run
```

### Web GUI

The GUI needs the source repo (the React frontend is **not** shipped on PyPI), plus the optional web backend dependencies:

```bash
git clone https://github.com/odafeng/sub-checker.git
cd sub-checker
pip install -e ".[web]"          # backend: FastAPI + uvicorn

# Start backend
uvicorn sub_checker.api:app --reload

# Start frontend (in another terminal)
cd frontend && npm install && npm run dev
```

Open `http://localhost:5173` — upload a `.docx`, pick a journal, run, and view the report with confidence badges and filtered false positives.

### CLI options

```
sub-check [OPTIONS] MANUSCRIPT_PATH

Arguments:
  MANUSCRIPT_PATH    Path to .docx file or directory containing one (optional with --init)

Options:
  -j, --journal      Target journal name (e.g. "The Lancet")
  -c, --config       Path to a config file (default: ./.sub-checker.yaml if present)
  -o, --output       terminal | json | markdown | html (default: terminal)
  --output-file      Write report to file
  --lang             Report language: en (default) or zh-TW
  --only             Comma-separated: typo,logic,figure,citation,format,guidelines,claim
  --skip             Comma-separated checkers to skip
  -v, --verbose      Show agent tool calls in real-time
  --dry-run          Only parse .docx, don't run agents
  --init             Generate default .sub-checker.yaml
```

## Pipeline (Plan-Execute-Verify)

```
Checkers   │  7 agents run concurrently (global concurrency cap, default 3 at a time)
Validate   │  Deterministic post-validation (date math, citation cross-check)
Review     │  Reviewer agent scores every surviving finding → confidence
Dedup      │  Same issue from multiple checkers collapsed to the highest-confidence one
```

- **Pre-execution**: deterministic citation pre-scan + multi-source reference verification
- **Post-validation**: false positives filtered, remaining findings get confidence scores (0-100%), cross-checker duplicates merged
- See [harness-architecture.md](docs/harness-architecture.md) for full technical details

## HTML report features

- Dark-themed styled report with severity badges
- **Confidence scores** — each finding shows reviewer-assigned confidence (%)
- **False positive filtering** — deterministic + reviewer agent removes incorrect findings
- **Chain of Thought viewer** — expand to see every API call, tool use, and reasoning step
- **Model display** — shows which Claude model generated the report
- i18n support (English / Traditional Chinese)

## Cost estimate

By default judgment-heavy checkers (logic, citation_claim, journal_guidelines) and the
reviewer run on **Claude Opus 4.8**, while mechanical checkers (typo, figure, citation_exist,
citation_format) run on the cheaper **Claude Sonnet 4.6**. Per-checker `effort` is tuned to
keep token use low. Measured on a real ~5,000-word, 25-reference manuscript:

| Scope | Agents | Time | Cost |
|-------|--------|------|------|
| Quick check | `--only figure,citation` | ~3 min | ~$1 |
| Standard | `--skip claim` | ~6 min | ~$2–3 |
| Full check | all 7 agents + harness | ~10–12 min | ~$3–5 |

Cost scales with manuscript length and reference count (citation_claim verifies each
reference against PubMed/Semantic Scholar/Crossref). Override any model in
`.sub-checker.yaml` (e.g. set everything to `claude-sonnet-4-6` for cheaper runs).

## Logging

All logs are stored in `~/.sub-checker/`:

- `logs/sub-checker.log` — application log (auto-rotated, 10MB x 5)
- `logs/sub-checker.error.log` — errors only
- `cot/` — agent chain-of-thought JSON logs (every tool call, every response)

Set `cot_dir: "disabled"` in `.sub-checker.yaml` to turn off COT file logging (entries still appear in HTML reports).

## Architecture

- **Plan-Execute-Verify harness**: concurrent checkers → deterministic validation → reviewer → dedup ([ADR-0010](docs/adr/0010-plan-execute-verify-harness.md))
- 7 agents + reviewer agent, each with system prompt + curated tools + agentic loop ([ADR-0002](docs/adr/0002-agent-per-checker-architecture.md))
- Parser provides raw data; agents judge document structure ([ADR-0009](docs/adr/0009-agent-over-deterministic-parsing.md))
- Multi-source citation verification: PubMed + Semantic Scholar + Crossref ([ADR-0005](docs/adr/0005-semantic-scholar-fallback.md))
- FastAPI + React + TypeScript GUI ([ADR-0006](docs/adr/0006-fastapi-react-gui.md))
- [Benchmark comparison](docs/benchmark-comparison.md) | [Harness architecture](docs/harness-architecture.md)

## License

MIT
