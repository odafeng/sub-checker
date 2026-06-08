from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click
from rich.console import Console

from sub_checker.config import DEFAULT_CONFIG_YAML, Config, load_config
from sub_checker.logging_config import setup_logging
from sub_checker.models import Severity
from sub_checker.parsers.docx_parser import parse_docx
from sub_checker.pipeline import run_pipeline


def _load_dotenv() -> None:
    """Load .env file from CWD or project root if it exists."""
    for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
            break


ALL_CHECKER_NAMES = ["typo", "logic", "figure", "citation", "format", "guidelines", "claim"]

# Map short names to agent names
NAME_MAP = {
    "typo": "typo_grammar",
    "logic": "logic",
    "figure": "figure_table",
    "citation": "citation_exist",
    "format": "citation_format",
    "guidelines": "journal_guidelines",
    "claim": "citation_claim",
}


def _resolve_names(names: str | None) -> set[str] | None:
    if not names:
        return None
    result = set()
    for n in names.split(","):
        n = n.strip()
        if n in NAME_MAP:
            result.add(NAME_MAP[n])
        else:
            result.add(n)
    return result


def _create_agents(config: Config) -> list:
    """Lazily import and instantiate all checker agents."""
    from sub_checker.agents.citation_claim import CitationClaimAgent
    from sub_checker.agents.citation_exist import CitationExistAgent
    from sub_checker.agents.citation_format import CitationFormatAgent
    from sub_checker.agents.figure_table import FigureTableAgent
    from sub_checker.agents.journal_guidelines import JournalGuidelinesAgent
    from sub_checker.agents.logic import LogicAgent
    from sub_checker.agents.typo_grammar import TypoGrammarAgent

    model = config.model
    return [
        TypoGrammarAgent(model=model),
        FigureTableAgent(model=model),
        CitationExistAgent(model=model),
        CitationFormatAgent(model=model),
        JournalGuidelinesAgent(model=model),
        LogicAgent(model=model),
        CitationClaimAgent(model=model),
    ]


@click.command()
@click.argument("manuscript_path", type=click.Path(exists=True))
@click.option("-j", "--journal", default=None, help="Target journal name")
@click.option(
    "-c", "--config", "config_path", default=None, type=click.Path(), help="Config file path"
)
@click.option(
    "-o",
    "--output",
    "output_format",
    default="terminal",
    type=click.Choice(["terminal", "json", "markdown", "html"]),
)
@click.option("--output-file", default=None, type=click.Path(), help="Write report to file")
@click.option(
    "--only", default=None, help=f"Comma-separated checkers: {','.join(ALL_CHECKER_NAMES)}"
)
@click.option("--skip", default=None, help="Comma-separated checkers to skip")
@click.option("-v", "--verbose", is_flag=True, help="Show agent tool calls")
@click.option("--dry-run", is_flag=True, help="Only parse .docx, don't run agents")
@click.option("--init", "do_init", is_flag=True, help="Generate default .sub-checker.yaml")
@click.option(
    "--lang",
    default="en",
    type=click.Choice(["en", "zh-TW"]),
    help="Report language (en or zh-TW)",
)
def main(
    manuscript_path: str,
    journal: str | None,
    config_path: str | None,
    output_format: str,
    output_file: str | None,
    only: str | None,
    skip: str | None,
    verbose: bool,
    dry_run: bool,
    do_init: bool,
    lang: str,
) -> None:
    """Check a manuscript before journal submission."""
    _load_dotenv()
    console = Console()

    # Initialize logging
    setup_logging(verbose=verbose)

    if do_init:
        init_path = Path(".sub-checker.yaml")
        init_path.write_text(DEFAULT_CONFIG_YAML)
        console.print(f"[green]Created {init_path}[/green]")
        return

    # Load config
    cfg_path = Path(config_path) if config_path else Path(".sub-checker.yaml")
    config = load_config(cfg_path if cfg_path.exists() else None)
    if journal:
        config.journal = journal

    # Parse manuscript
    ms_path = Path(manuscript_path)
    if ms_path.is_dir():
        docx_files = list(ms_path.glob("*.docx"))
        if not docx_files:
            console.print("[red]No .docx file found in directory.[/red]")
            raise SystemExit(1)
        # Prefer files with "manuscript" in the name
        manuscript_files = [f for f in docx_files if "manuscript" in f.name.lower()]
        docx_path = manuscript_files[0] if manuscript_files else docx_files[0]
        figure_dir = ms_path / config.figures.dir
        # Fall back to the directory itself if no figures/ subdir
        if not figure_dir.exists():
            figure_dir = ms_path
    else:
        docx_path = ms_path
        figure_dir = ms_path.parent / config.figures.dir
        if not figure_dir.exists():
            figure_dir = ms_path.parent

    console.print(f"Parsing [bold]{docx_path.name}[/bold]...")
    manuscript = parse_docx(docx_path, figure_dir if figure_dir.exists() else None)

    if dry_run:
        console.print(f"\n[bold]Title:[/bold] {manuscript.title}")
        console.print(f"[bold]Sections:[/bold] {len(manuscript.sections)}")
        for s in manuscript.sections:
            console.print(f"  {'  ' * (s.level - 1)}{s.heading} ({len(s.paragraphs)} paragraphs)")
        console.print(f"[bold]Total paragraphs:[/bold] {len(manuscript.paragraphs)}")
        console.print(f"[bold]Word count:[/bold] {len(manuscript.raw_text.split())}")
        console.print(f"[bold]Has references:[/bold] {manuscript.reference_section is not None}")
        console.print(f"[bold]Figure dir:[/bold] {manuscript.figure_dir}")
        return

    # Run pipeline
    agents = _create_agents(config)
    report = asyncio.run(
        run_pipeline(
            manuscript,
            config,
            agents,
            verbose=verbose,
            skip=_resolve_names(skip),
            only=_resolve_names(only),
        )
    )

    # Output report
    if output_format == "terminal":
        from sub_checker.reporters.terminal import print_report

        print_report(report, console, lang=lang)
    elif output_format == "json":
        from sub_checker.reporters.json_reporter import format_json

        text = format_json(report)
        if output_file:
            Path(output_file).write_text(text)
        else:
            console.print(text)
    elif output_format == "markdown":
        from sub_checker.reporters.markdown_reporter import format_markdown

        text = format_markdown(report, lang=lang)
        if output_file:
            Path(output_file).write_text(text)
        else:
            console.print(text)
    elif output_format == "html":
        from sub_checker.reporters.html_reporter import format_html

        text = format_html(report, lang=lang)
        out = Path(output_file) if output_file else Path("sub-check-report.html")
        out.write_text(text)
        console.print(f"[green]HTML report saved to {out}[/green]")

    # Exit code based on errors
    error_count = report.summary.get(Severity.ERROR, 0)
    if error_count > 0:
        raise SystemExit(1)
