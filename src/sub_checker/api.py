"""FastAPI backend for sub-checker GUI."""

from __future__ import annotations

import contextlib
import json
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse

from sub_checker.config import Config
from sub_checker.env import load_dotenv
from sub_checker.i18n import checker_display_name
from sub_checker.models import Manuscript, Report
from sub_checker.orchestrator import build_report, create_agents, filter_agents, run_all_phases
from sub_checker.parsers.docx_parser import parse_docx
from sub_checker.reporters.html_reporter import format_html
from sub_checker.reporters.json_reporter import format_json

load_dotenv()

_MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

app = FastAPI(title="Sub-Checker API", version="0.1.0")

_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:5174",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Store active runs for WebSocket progress and completed reports
_active_runs: dict[str, dict[str, Any]] = {}
_SESSION_TTL = 3600  # 1 hour


def _cleanup_stale_sessions() -> None:
    """Remove sessions older than TTL and their temp dirs."""
    now = time.monotonic()
    stale = [
        sid
        for sid, data in _active_runs.items()
        if now - data.get("created_at", now) > _SESSION_TTL
    ]
    for sid in stale:
        tmp_dir = _active_runs[sid].get("tmp_dir")
        if tmp_dir:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        del _active_runs[sid]


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
        raise HTTPException(status_code=400, detail="Please upload a .docx file")

    # Sanitize filename before creating any temp resources
    safe_name = Path(file.filename).name
    if not safe_name or safe_name != file.filename.replace("\\", "/").split("/")[-1]:
        raise HTTPException(status_code=400, detail="Invalid filename")

    content = await file.read()
    if len(content) > _MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {_MAX_UPLOAD_BYTES // (1024 * 1024)} MB)",
        )

    session_id = uuid.uuid4().hex[:12]
    tmp_dir = Path(tempfile.mkdtemp(prefix=f"subcheck_{session_id}_"))
    try:
        docx_path = tmp_dir / safe_name
        if not docx_path.resolve().is_relative_to(tmp_dir.resolve()):
            raise ValueError("Invalid filename")
        docx_path.write_bytes(content)
        manuscript = parse_docx(docx_path, tmp_dir)
    except Exception as e:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Failed to process manuscript: {e}") from e

    _cleanup_stale_sessions()
    _active_runs[session_id] = {
        "manuscript": manuscript,
        "docx_path": str(docx_path),
        "tmp_dir": str(tmp_dir),
        "created_at": time.monotonic(),
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


@app.websocket("/ws/check/{session_id}")
async def websocket_check(websocket: WebSocket, session_id: str) -> None:
    """WebSocket endpoint for running checks with real-time progress."""
    # Check Origin header to prevent cross-site WebSocket hijacking
    origin = (websocket.headers.get("origin") or "").rstrip("/")
    if origin and origin not in _ALLOWED_ORIGINS:
        await websocket.close(code=4003)
        return
    await websocket.accept()

    if session_id not in _active_runs:
        await websocket.send_json({"type": "error", "message": "Invalid session_id"})
        await websocket.close()
        return

    try:
        config_msg = await websocket.receive_json()
        journal = config_msg.get("journal", "")
        selected = set(config_msg.get("checkers", []))
        lang = config_msg.get("lang", "en")

        run_data = _active_runs[session_id]
        manuscript: Manuscript = run_data["manuscript"]

        config = Config(output_lang=lang)
        if journal:
            config.journal = journal

        agents = filter_agents(create_agents(config), only=selected or None)

        await websocket.send_json(
            {"type": "run_start", "total_agents": len(agents), "agents": [a.name for a in agents]}
        )

        # Progress callback → WebSocket
        async def on_progress(event: str, agent_name: str, data: dict[str, Any]) -> None:
            await websocket.send_json({"type": event, "agent": agent_name, **data})

        results, harness_usage = await run_all_phases(agents, manuscript, config, on_progress)
        report = build_report(
            results,
            run_data["docx_path"],
            config.journal,
            model=config.model,
            harness_usage=harness_usage,
        )

        # Store report for later retrieval via REST endpoint
        _active_runs[session_id]["report"] = report

        report_json = json.loads(format_json(report))
        for r in report_json["results"]:
            r["display_name"] = checker_display_name(r["checker"], lang)

        await websocket.send_json(
            {"type": "report", "data": report_json, "html": format_html(report, lang=lang)}
        )

    except WebSocketDisconnect:
        pass
    except Exception as e:
        with contextlib.suppress(Exception):
            await websocket.send_json({"type": "error", "message": str(e)})


@app.get("/api/report/{session_id}/html")
async def get_html_report(session_id: str, lang: str = "en") -> HTMLResponse:
    """Get the HTML report for a completed session."""
    run_data = _active_runs.get(session_id, {})
    if "report" not in run_data:
        return HTMLResponse("<h1>Report not found</h1>", status_code=404)
    report: Report = run_data["report"]
    return HTMLResponse(format_html(report, lang=lang))
