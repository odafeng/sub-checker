"""Regression evaluation runner for private manuscript cases.

Runs the full pipeline against locally stored manuscripts (never committed —
the cases directory is gitignored) with hand-labelled golden findings, and
measures harness quality:

- recall: expected findings that survived the pipeline
- wrongly filtered: expected findings the harness killed (worst failure mode)
- leakage: known false positives that escaped the harness
- noise: surviving findings not matched by any expectation

Case layout (one directory per case):

    eval/cases/<case-name>/
        manuscript.docx     # the private manuscript
        golden.yaml         # hand-labelled expectations (see GoldenCase)
        figures/            # optional figure dir

The cases directory defaults to ./eval/cases or $SUB_CHECKER_EVAL_DIR.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import yaml
from rich.console import Console
from rich.table import Table

from sub_checker.config import Config, load_config
from sub_checker.env import load_dotenv
from sub_checker.models import Finding
from sub_checker.orchestrator import build_report, create_agents, filter_agents, run_all_phases
from sub_checker.parsers.docx_parser import parse_docx


@dataclass
class Matcher:
    """Matches findings by content. All specified conditions must hold."""

    keywords: list[str] = field(default_factory=list)  # all must appear, case-insensitive
    checker: str | None = None
    claim_type: str | None = None
    ref_number: int | None = None

    def matches(self, f: Finding) -> bool:
        if self.checker and f.checker != self.checker:
            return False
        if self.claim_type and f.claim_type != self.claim_type:
            return False
        if self.ref_number is not None and f.ref_number != self.ref_number:
            return False
        text = " ".join(filter(None, [f.message, f.suggestion, f.context])).lower()
        return all(kw.lower() in text for kw in self.keywords)


@dataclass
class GoldenItem:
    id: str
    matcher: Matcher
    description: str = ""


@dataclass
class GoldenCase:
    """Hand-labelled expectations for one manuscript."""

    journal: str | None = None
    checkers: list[str] | None = None  # restrict the run (like --only)
    lang: str = "en"
    expected: list[GoldenItem] = field(default_factory=list)  # must survive the pipeline
    forbidden: list[GoldenItem] = field(default_factory=list)  # known FPs, must NOT survive


@dataclass
class CaseOutcome:
    name: str
    found: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    wrongly_filtered: list[str] = field(default_factory=list)  # true findings the harness killed
    leaked: list[str] = field(default_factory=list)  # known FPs that survived
    caught_fps: list[str] = field(default_factory=list)  # known FPs correctly filtered
    noise: int = 0  # surviving findings not matching any expectation
    cost: float = 0.0
    elapsed: float = 0.0
    error: str = ""

    @property
    def passed(self) -> bool:
        return not (self.missed or self.wrongly_filtered or self.leaked or self.error)


def _parse_item(raw: dict[str, Any], idx: int) -> GoldenItem:
    return GoldenItem(
        id=str(raw.get("id", f"item-{idx}")),
        description=str(raw.get("description", "")),
        matcher=Matcher(
            keywords=[str(k) for k in raw.get("keywords", [])],
            checker=raw.get("checker"),
            claim_type=raw.get("claim_type"),
            ref_number=raw.get("ref_number"),
        ),
    )


def load_golden(path: Path) -> GoldenCase:
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return GoldenCase(
        journal=data.get("journal"),
        checkers=data.get("checkers"),
        lang=data.get("lang", "en"),
        expected=[_parse_item(r, i) for i, r in enumerate(data.get("expected", []))],
        forbidden=[_parse_item(r, i) for i, r in enumerate(data.get("forbidden", []))],
    )


def evaluate_case(all_findings: list[Finding], golden: GoldenCase, name: str) -> CaseOutcome:
    """Compare pipeline output (including filtered findings) against the golden labels."""
    outcome = CaseOutcome(name=name)
    surviving = [f for f in all_findings if f.validation_status != "filtered"]
    filtered = [f for f in all_findings if f.validation_status == "filtered"]

    matched_surviving: set[int] = set()
    for item in golden.expected:
        hit = [i for i, f in enumerate(surviving) if item.matcher.matches(f)]
        if hit:
            outcome.found.append(item.id)
            matched_surviving.update(hit)
        elif any(item.matcher.matches(f) for f in filtered):
            outcome.wrongly_filtered.append(item.id)
        else:
            outcome.missed.append(item.id)

    for item in golden.forbidden:
        hit = [i for i, f in enumerate(surviving) if item.matcher.matches(f)]
        if hit:
            outcome.leaked.append(item.id)
            matched_surviving.update(hit)  # leaked FPs are not "noise", they're tracked
        elif any(item.matcher.matches(f) for f in filtered):
            outcome.caught_fps.append(item.id)

    outcome.noise = sum(1 for i in range(len(surviving)) if i not in matched_surviving)
    return outcome


async def run_case(case_dir: Path, base_config: Config) -> CaseOutcome:
    """Run the full pipeline for one case and evaluate it."""
    name = case_dir.name
    golden = load_golden(case_dir / "golden.yaml")

    docx_files = sorted(case_dir.glob("*.docx"))
    if not docx_files:
        return CaseOutcome(name=name, error="no .docx file in case directory")

    figure_dir = case_dir / "figures"
    manuscript = parse_docx(docx_files[0], figure_dir if figure_dir.exists() else case_dir)

    config = base_config.model_copy(deep=True)
    config.journal = golden.journal
    config.output_lang = golden.lang

    agents = filter_agents(
        create_agents(config), only=set(golden.checkers) if golden.checkers else None
    )

    start = time.monotonic()
    results, harness_usage = await run_all_phases(agents, manuscript, config)
    elapsed = time.monotonic() - start

    report = build_report(
        results,
        manuscript_path=str(docx_files[0]),
        journal=config.journal,
        model=config.model,
        harness_usage=harness_usage,
        harness_model=config.reviewer_model or config.model,
    )

    all_findings = [f for r in results for f in r.findings]
    outcome = evaluate_case(all_findings, golden, name)
    outcome.cost = report.total_cost
    outcome.elapsed = elapsed
    return outcome


def _print_outcomes(console: Console, outcomes: list[CaseOutcome]) -> None:
    table = Table(title="Harness Regression Results")
    table.add_column("Case")
    table.add_column("Recall")
    table.add_column("Wrongly filtered", style="red")
    table.add_column("FP leaked", style="yellow")
    table.add_column("FP caught", style="green")
    table.add_column("Noise")
    table.add_column("Cost")
    table.add_column("Time")
    table.add_column("Status")

    for o in outcomes:
        if o.error:
            table.add_row(o.name, "—", "—", "—", "—", "—", "—", "—", f"[red]{o.error}[/red]")
            continue
        total_expected = len(o.found) + len(o.missed) + len(o.wrongly_filtered)
        recall = f"{len(o.found)}/{total_expected}" if total_expected else "n/a"
        status = "[green]PASS[/green]" if o.passed else "[red]FAIL[/red]"
        table.add_row(
            o.name,
            recall,
            ", ".join(o.wrongly_filtered) or "0",
            ", ".join(o.leaked) or "0",
            str(len(o.caught_fps)),
            str(o.noise),
            f"${o.cost:.2f}",
            f"{o.elapsed:.0f}s",
            status,
        )

    console.print(table)
    for o in outcomes:
        if o.missed:
            console.print(f"[yellow]{o.name}: missed expected findings: {o.missed}[/yellow]")
        if o.wrongly_filtered:
            console.print(
                f"[red]{o.name}: harness FILTERED true findings: {o.wrongly_filtered}[/red]"
            )
        if o.leaked:
            console.print(f"[yellow]{o.name}: false positives leaked: {o.leaked}[/yellow]")


@click.command()
@click.argument("cases_dir", required=False, type=click.Path())
@click.option("--case", "case_name", default=None, help="Run a single case by directory name")
@click.option(
    "-c", "--config", "config_path", default=None, type=click.Path(), help="Config file path"
)
@click.option("--output", "output_file", default=None, type=click.Path(), help="Write JSON results")
def main(
    cases_dir: str | None,
    case_name: str | None,
    config_path: str | None,
    output_file: str | None,
) -> None:
    """Run the harness regression suite against private local manuscript cases.

    CASES_DIR defaults to $SUB_CHECKER_EVAL_DIR, then ./eval/cases.
    """
    load_dotenv()
    console = Console()

    root = Path(cases_dir or os.environ.get("SUB_CHECKER_EVAL_DIR") or "eval/cases")
    if not root.is_dir():
        console.print(
            f"[red]Cases directory not found: {root}[/red]\n"
            "Create it (it is gitignored) and add case directories — see eval/README.md.\n"
            "You can generate a synthetic example with: python eval/make_example_case.py"
        )
        raise SystemExit(2)

    case_dirs = sorted(d for d in root.iterdir() if d.is_dir() and (d / "golden.yaml").exists())
    if case_name:
        case_dirs = [d for d in case_dirs if d.name == case_name]
    if not case_dirs:
        console.print(f"[red]No cases with golden.yaml found in {root}[/red]")
        raise SystemExit(2)

    # An explicitly passed --config that doesn't exist is an error — silently
    # running the whole (expensive) eval suite on defaults would be worse.
    if config_path:
        cfg_path = Path(config_path)
        if not cfg_path.exists():
            console.print(f"[red]Config file not found: {cfg_path}[/red]")
            raise SystemExit(2)
        base_config = load_config(cfg_path)
    else:
        default_cfg = Path(".sub-checker.yaml")
        base_config = load_config(default_cfg if default_cfg.exists() else None)

    async def run_all() -> list[CaseOutcome]:
        outcomes = []
        for d in case_dirs:
            console.print(f"Running case [bold]{d.name}[/bold]...")
            try:
                outcomes.append(await run_case(d, base_config))
            except Exception as e:  # one broken case must not kill the suite
                outcomes.append(CaseOutcome(name=d.name, error=str(e)))
        return outcomes

    outcomes = asyncio.run(run_all())
    _print_outcomes(console, outcomes)

    if output_file:
        payload = [
            {
                "case": o.name,
                "found": o.found,
                "missed": o.missed,
                "wrongly_filtered": o.wrongly_filtered,
                "leaked": o.leaked,
                "caught_fps": o.caught_fps,
                "noise": o.noise,
                "cost": round(o.cost, 4),
                "elapsed_seconds": round(o.elapsed, 1),
                "passed": o.passed,
                "error": o.error,
            }
            for o in outcomes
        ]
        Path(output_file).write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        console.print(f"Results written to {output_file}")

    if not all(o.passed for o in outcomes):
        raise SystemExit(1)
