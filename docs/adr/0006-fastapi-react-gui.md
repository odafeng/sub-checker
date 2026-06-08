# 6. FastAPI + React GUI

## Status

Accepted

## Context

The CLI is effective for developers but not accessible to researchers unfamiliar with terminals. A GUI lowers the barrier to adoption. We considered Streamlit (fast to build), Gradio (simplest), and FastAPI + React SPA (most flexible). The user preferred FastAPI + React for maximum control over UX.

## Decision

- **Backend**: FastAPI serving REST endpoints (`/api/upload`, `/api/checkers`) and a WebSocket endpoint (`/ws/check/{session_id}`) for real-time agent progress.
- **Frontend**: React 19 + TypeScript + Tailwind CSS v4 + Vite. Four-step flow: Upload → Configure → Running → Report.
- **Communication**: WebSocket pushes `agent_start`, `agent_done`, `agent_error`, `phase_start`, and final `report` messages. Frontend renders progress in real-time.
- **Report delivery**: Backend generates both JSON (for card view) and HTML (for iframe embed + download).
- **Dev workflow**: `vite dev` proxies `/api` and `/ws` to FastAPI on port 8000.

The backend reuses the shared `orchestrator.py` — no duplicated run logic.

## Consequences

- **Positive**: Full control over UX — animated progress, collapsible sections, language switcher.
- **Positive**: WebSocket gives real-time feedback (which agent is running, findings count as they complete).
- **Positive**: Frontend is independently deployable (static build via `vite build`).
- **Negative**: Significantly more code than Streamlit (~500 lines React + ~150 lines API).
- **Negative**: Two dev servers during development (FastAPI + Vite).
- **Negative**: No authentication — currently trusts all requests. Would need auth for public deployment.
