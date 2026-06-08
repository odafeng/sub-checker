"""FastAPI backend for sub-checker GUI."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from sub_checker.agents.base import BaseCheckerAgent
from sub_checker.config import Config
from sub_checker.i18n import checker_display_name
from sub_checker.models import CheckerResult, Finding, Manuscript, Report, Severity
from sub_checker.parsers.docx_parser import parse_docx
from sub_checker.reporters.html_reporter import format_html
from sub_checker.reporters.json_reporter import format_json


def _load_dotenv() -> None:
    """Load .env from CWD or project root."""
    for candidate in [Path.cwd() / ".env", Path(__file__).parent.parent.parent / ".env"]:
        if candidate.exists():
            for line in candidate.read_text().splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())
            break


_load_dotenv()

app = FastAPI(title="Sub-Checker API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active runs for WebSocket progress
_active_runs: dict[str, dict[str, Any]] = {}


def _create_agents(config: Config) -> list[BaseCheckerAgent]:
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


ALL_CHECKERS = [
    {"name": "typo_grammar", "label_en": "Typo & Grammar", "label_zh": "拼字與文法"},
    {"name": "figure_table", "label_en": "Figure & Table", "label_zh": "圖表檢查"},
    {"name": "citation_exist", "label_en": "Citation Existence", "label_zh": "引用完整性"},
    {"name": "citation_format", "label_en": "Citation Format", "label_zh": "引用格式"},
    {"name": "journal_guidelines", "label_en": "Journal Guidelines", "label_zh": "期刊投稿規範"},
    {"name": "logic", "label_en": "Logic Consistency", "label_zh": "邏輯一致性"},
    {"name": "citation_claim", "label_en": "Citation-Claim", "label_zh": "引用-主張驗證"},
]


@app.get("/api/checkers")
async def list_checkers() -> list[dict]:
    return ALL_CHECKERS


@app.post("/api/upload")
async def upload_manuscript(file: UploadFile) -> dict:
    """Upload a .docx file. Returns a session_id and parsed metadata."""
    if not file.filename or not file.filename.endswith(".docx"):
        return {"error": "Please upload a .docx file"}

    session_id = uuid.uuid4().hex[:12]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"subcheck_{session_id}_"))
    docx_path = tmp_dir / file.filename
    docx_path.write_bytes(await file.read())

    manuscript = parse_docx(docx_path, tmp_dir)

    _active_runs[session_id] = {
        "manuscript": manuscript,
        "docx_path": str(docx_path),
        "tmp_dir": str(tmp_dir),
    }

    return {
        "session_id": session_id,
        "filename": file.filename,
        "title": manuscript.title,
        "sections": [s.heading for s in manuscript.sections],
        "word_count": len(manuscript.raw_text.split()),
        "paragraph_count": len(manuscript.paragraphs),
        "has_references": manuscript.reference_section is not None,
    }


async def _run_agent_with_progress(
    agent: BaseCheckerAgent,
    manuscript: Manuscript,
    config: Config,
    ws: WebSocket,
) -> CheckerResult:
    """Run agent and send progress updates via WebSocket."""
    await ws.send_json({"type": "agent_start", "agent": agent.name})
    try:
        result = await agent.run(manuscript, config)
        await ws.send_json(
            {
                "type": "agent_done",
                "agent": agent.name,
                "findings_count": len(result.findings),
                "elapsed": round(result.elapsed_seconds, 1),
            }
        )
        return result
    except Exception as e:
        await ws.send_json({"type": "agent_error", "agent": agent.name, "error": str(e)})
        return CheckerResult(
            checker_name=agent.name,
            findings=[
                Finding(checker=agent.name, severity=Severity.ERROR, message=f"Agent crashed: {e}")
            ],
        )


@app.websocket("/ws/check/{session_id}")
async def websocket_check(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for running checks with real-time progress."""
    await websocket.accept()

    if session_id not in _active_runs:
        await websocket.send_json({"type": "error", "message": "Invalid session_id"})
        await websocket.close()
        return

    try:
        # Receive configuration from client
        config_msg = await websocket.receive_json()
        journal = config_msg.get("journal", "")
        selected = set(config_msg.get("checkers", []))
        lang = config_msg.get("lang", "en")

        run_data = _active_runs[session_id]
        manuscript: Manuscript = run_data["manuscript"]

        config = Config(output_lang=lang)
        if journal:
            config.journal = journal

        # Create and filter agents
        agents = _create_agents(config)
        if selected:
            agents = [a for a in agents if a.name in selected]

        await websocket.send_json(
            {
                "type": "run_start",
                "total_agents": len(agents),
                "agents": [a.name for a in agents],
            }
        )

        # Phase execution
        phase_groups = [
            {"typo_grammar", "figure_table", "citation_exist"},
            {"citation_format", "journal_guidelines", "logic"},
            {"citation_claim"},
        ]

        from datetime import UTC, datetime

        results: list[CheckerResult] = []
        for phase_num, phase_names in enumerate(phase_groups, 1):
            phase_agents = [a for a in agents if a.name in phase_names]
            if not phase_agents:
                continue

            await websocket.send_json(
                {
                    "type": "phase_start",
                    "phase": phase_num,
                    "agents": [a.name for a in phase_agents],
                }
            )

            phase_results = await asyncio.gather(
                *[_run_agent_with_progress(a, manuscript, config, websocket) for a in phase_agents]
            )
            results.extend(phase_results)

        # Build report
        summary: dict[Severity, int] = {s: 0 for s in Severity}
        total_cost = 0.0
        for r in results:
            for f in r.findings:
                summary[f.severity] = summary.get(f.severity, 0) + 1
            total_cost += (
                r.token_usage.input_tokens * 3 + r.token_usage.output_tokens * 15
            ) / 1_000_000

        report = Report(
            manuscript_path=run_data["docx_path"],
            timestamp=datetime.now(UTC),
            target_journal=config.journal,
            results=results,
            summary=summary,
            total_cost=total_cost,
        )

        # Send final report
        report_json = json.loads(format_json(report))
        # Add localized checker names
        for r in report_json["results"]:
            r["display_name"] = checker_display_name(r["checker"], lang)

        await websocket.send_json(
            {
                "type": "report",
                "data": report_json,
                "html": format_html(report, lang=lang),
            }
        )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})


@app.get("/api/report/{session_id}/html")
async def get_html_report(session_id: str, lang: str = "en") -> HTMLResponse:
    """Get the HTML report for a completed session."""
    if session_id not in _active_runs or "report" not in _active_runs.get(session_id, {}):
        return HTMLResponse("<h1>Report not found</h1>", status_code=404)
    report = _active_runs[session_id]["report"]
    return HTMLResponse(format_html(report, lang=lang))
