"""Tests for the FastAPI upload/websocket entry points (security guards)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi")
from starlette.testclient import TestClient

from sub_checker.api import app

client = TestClient(app)


def test_upload_rejects_non_docx():
    resp = client.post("/api/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert resp.status_code == 400


def test_upload_rejects_backslash_path_filename():
    # A Windows-style traversal filename passes the .docx extension check but
    # must be rejected by the basename cross-check before any temp file is made.
    resp = client.post(
        "/api/upload",
        files={"file": ("..\\..\\evil.docx", b"x", "application/octet-stream")},
    )
    assert resp.status_code == 400


def test_upload_rejects_too_large():
    big = b"x" * (20 * 1024 * 1024 + 1)
    resp = client.post("/api/upload", files={"file": ("big.docx", big, "application/octet-stream")})
    assert resp.status_code == 413


def test_upload_accepts_docx_and_returns_session(sample_docx: Path):
    resp = client.post(
        "/api/upload",
        files={"file": ("manuscript.docx", sample_docx.read_bytes(), "application/octet-stream")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["session_id"]
    assert body["title"]
    assert body["has_references"] is True


def test_websocket_rejects_invalid_session():
    with client.websocket_connect("/ws/check/does-not-exist") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "error"
