# sub-checker

Pre-submission manuscript checker powered by Claude agents. Each check is performed by a specialized AI agent that reads your manuscript through structured tools, so it understands context far better than regex-based linters.

## What it checks

| Agent | What it does |
|-------|-------------|
| **typo_grammar** | Spelling, grammar, awkward phrasing (skips reference list) |
| **figure_table** | Figure/table references exist, numbering is sequential, files present |
| **citation_exist** | In-text citations match the reference list (and vice versa) |
| **citation_format** | Reference list follows target journal's citation style (APA, Vancouver, AMA, etc.) |
| **journal_guidelines** | Word count, required sections, abstract format, required statements (COI, ethics, data availability) |
| **logic** | Contradictions, unsupported claims, methods-results mismatches |
| **citation_claim** | Fetches cited paper abstracts from PubMed (with Semantic Scholar fallback), verifies they support your claims |

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

```bash
# Full check with target journal
sub-check ./manuscript/ -j "The Lancet"

# Check a specific .docx file
sub-check paper.docx -j "Nature Medicine"

# Only run specific checkers (cheaper & faster)
sub-check paper.docx --only figure,citation

# Skip expensive checkers
sub-check paper.docx --skip claim,logic

# Output as styled HTML report
sub-check paper.docx -o html --output-file report.html

# Output as JSON (for programmatic use)
sub-check paper.docx -o json --output-file report.json

# Dry run (just parse, no agents)
sub-check paper.docx --dry-run
```

### CLI options

```
sub-check [OPTIONS] MANUSCRIPT_PATH

Arguments:
  MANUSCRIPT_PATH    Path to .docx file or directory containing one

Options:
  -j, --journal      Target journal name (e.g. "The Lancet")
  -o, --output       terminal | json | markdown | html (default: terminal)
  --output-file      Write report to file
  --only             Comma-separated: typo,logic,figure,citation,format,guidelines,claim
  --skip             Comma-separated checkers to skip
  -v, --verbose      Show agent tool calls in real-time
  --dry-run          Only parse .docx, don't run agents
  --init             Generate default .sub-checker.yaml
```

## Cost estimate

Uses Claude Sonnet by default. Approximate cost per manuscript (~4000 words):

| Scope | Agents | Time | Cost |
|-------|--------|------|------|
| Quick check | `--only figure,citation` | ~4 min | ~$1.50 |
| Standard | `--skip claim` | ~8 min | ~$3.50 |
| Full check | all 7 agents | ~12 min | ~$5.00 |

You can change the model in `.sub-checker.yaml` (e.g. use `claude-haiku-4-5-20251001` for cheaper runs).

## Logging

All logs are stored in `~/.sub-checker/`:

- `logs/sub-checker.log` — application log (auto-rotated, 10MB x 5)
- `logs/sub-checker.error.log` — errors only
- `cot/` — agent chain-of-thought JSON logs (every tool call, every response)

## License

MIT
