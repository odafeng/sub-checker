"""HTML reporter with styled output and i18n support."""

from __future__ import annotations

import html
import json

from sub_checker.i18n import checker_display_name, t
from sub_checker.models import Report, Severity

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
_SEVERITY_KEY = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info_label"}


def _esc(text: str | None) -> str:
    if not text:
        return "—"
    return html.escape(text)


def _severity_badge(severity: Severity, lang: str) -> str:
    css = {Severity.ERROR: "error", Severity.WARNING: "warning", Severity.INFO: "info"}
    label = t(_SEVERITY_KEY[severity], lang)
    return f'<span class="badge {css[severity]}">{label}</span>'


def _render_cot(entries: list[dict], lang: str) -> str:
    """Render COT entries as a collapsible details block."""
    if not entries:
        return ""
    label = "Chain of Thought" if lang != "zh-TW" else "Agent 推理過程"
    rows = []
    for e in entries:
        etype = e.get("type", "")
        ts = e.get("timestamp", "")[:19]  # trim to seconds
        if etype == "api_request":
            rows.append(
                f'<div class="cot-entry cot-request">'
                f'<span class="cot-ts">{ts}</span> '
                f'<span class="cot-tag">REQUEST</span> '
                f"{e.get('message_count', 0)} messages, {e.get('tool_count', 0)} tools"
                f"</div>"
            )
        elif etype == "api_response":
            blocks = e.get("content_blocks", [])
            detail = ""
            for b in blocks:
                if b.get("type") == "text":
                    text = _esc(b.get("text", "")[:300])
                    detail += f'<div class="cot-text">{text}</div>'
                elif b.get("type") == "tool_use":
                    tool = _esc(b.get("tool", ""))
                    inp = _esc(json.dumps(b.get("input", {}), ensure_ascii=False)[:200])
                    detail += f'<div class="cot-tool-call">{tool}({inp})</div>'
            rows.append(
                f'<div class="cot-entry cot-response">'
                f'<span class="cot-ts">{ts}</span> '
                f'<span class="cot-tag">RESPONSE</span> '
                f"stop={_esc(e.get('stop_reason', ''))}"
                f"{detail}</div>"
            )
        elif etype == "tool_result":
            preview = _esc(e.get("result_preview", "")[:200])
            rows.append(
                f'<div class="cot-entry cot-tool-result">'
                f'<span class="cot-ts">{ts}</span> '
                f'<span class="cot-tag">TOOL</span> '
                f"{_esc(e.get('tool_name', ''))}"
                f'<div class="cot-preview">{preview}</div>'
                f"</div>"
            )
        elif etype == "finding":
            rows.append(
                f'<div class="cot-entry cot-finding">'
                f'<span class="cot-ts">{ts}</span> '
                f'<span class="cot-tag">FINDING</span> '
                f"[{_esc(e.get('severity', ''))}] {_esc(e.get('message', '')[:150])}"
                f"</div>"
            )
        elif etype == "error":
            rows.append(
                f'<div class="cot-entry cot-error">'
                f'<span class="cot-ts">{ts}</span> '
                f'<span class="cot-tag">ERROR</span> '
                f"{_esc(e.get('error', ''))}"
                f"</div>"
            )
    return (
        f'<details class="cot-details">'
        f'<summary class="cot-summary">{label} ({len(entries)} steps)</summary>'
        f'<div class="cot-body">{"".join(rows)}</div>'
        f"</details>"
    )


def format_html(report: Report, lang: str = "en") -> str:
    errors = report.summary.get(Severity.ERROR, 0)
    warnings = report.summary.get(Severity.WARNING, 0)
    infos = report.summary.get(Severity.INFO, 0)
    total = errors + warnings + infos

    # Localized strings
    tr = lambda key: t(key, lang)  # noqa: E731

    # Build checker sections
    checker_sections = []
    for result in report.results:
        display = checker_display_name(result.checker_name, lang)
        findings_html = ""
        # Filter out findings marked as "filtered" by Phase 3 harness
        active_findings = [f for f in result.findings if f.validation_status != "filtered"]
        if not active_findings:
            findings_html = f'<p class="no-issues">{tr("no_issues")}</p>'
        else:
            sorted_findings = sorted(active_findings, key=lambda f: _SEVERITY_ORDER[f.severity])
            rows = []
            for f in sorted_findings:
                confidence_badge = ""
                if f.validation_status == "confirmed":
                    confidence_badge = (
                        f' <span class="confidence-badge confirmed">{f.confidence:.0%}</span>'
                    )
                elif f.validation_status == "downgraded":
                    confidence_badge = (
                        f' <span class="confidence-badge downgraded">{f.confidence:.0%}</span>'
                    )
                rows.append(
                    f"<tr>"
                    f'<td class="col-severity">{_severity_badge(f.severity, lang)}'
                    f"{confidence_badge}</td>"
                    f'<td class="col-location">{_esc(f.location)}</td>'
                    f'<td class="col-message">{_esc(f.message)}</td>'
                    f'<td class="col-suggestion">{_esc(f.suggestion)}</td>'
                    f"</tr>"
                )
            findings_html = (
                '<table class="findings-table">'
                f"<thead><tr>"
                f"<th>{tr('severity')}</th><th>{tr('location')}</th>"
                f"<th>{tr('message')}</th><th>{tr('suggestion')}</th>"
                f"</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                "</table>"
            )

        e = sum(1 for f in active_findings if f.severity == Severity.ERROR)
        w = sum(1 for f in active_findings if f.severity == Severity.WARNING)
        i = sum(1 for f in active_findings if f.severity == Severity.INFO)
        stats = []
        if e:
            stats.append(f'<span class="stat-error">{e} {tr("errors").lower()}</span>')
        if w:
            stats.append(f'<span class="stat-warning">{w} {tr("warnings").lower()}</span>')
        if i:
            stats.append(f'<span class="stat-info">{i} {tr("info").lower()}</span>')
        stats_html = (
            " · ".join(stats) if stats else f'<span class="stat-info">{tr("no_issues")}</span>'
        )

        cot_html = _render_cot(result.cot_entries, lang)

        checker_sections.append(
            f'<section class="checker">'
            f'<div class="checker-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">'
            f"<h2>{_esc(display)}</h2>"
            f'<div class="checker-meta">{stats_html} · {result.elapsed_seconds:.1f}s</div>'
            f"</div>"
            f'<div class="checker-body">{findings_html}{cot_html}</div>'
            f"</section>"
        )

    journal_html = (
        _esc(report.target_journal) if report.target_journal else tr("journal_not_specified")
    )
    timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M UTC")
    html_lang = "zh-Hant" if lang == "zh-TW" else "en"

    return f"""\
<!DOCTYPE html>
<html lang="{html_lang}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{tr("report_title")}</title>
<style>
  :root {{
    --bg: #0f1117;
    --surface: #1a1d27;
    --surface2: #232733;
    --border: #2e3348;
    --text: #e1e4ed;
    --text-dim: #8b90a5;
    --accent: #7c6ef0;
    --error: #f05365;
    --error-bg: rgba(240,83,101,0.1);
    --warning: #f0a73a;
    --warning-bg: rgba(240,167,58,0.1);
    --info: #5eb5f7;
    --info-bg: rgba(94,181,247,0.1);
    --success: #4ade80;
    --font: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    --mono: 'JetBrains Mono', 'Fira Code', 'SF Mono', Menlo, monospace;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--font);
    font-size: 14px;
    line-height: 1.6;
    padding: 2rem;
    max-width: 1200px;
    margin: 0 auto;
  }}
  h1 {{
    font-size: 1.75rem;
    font-weight: 700;
    background: linear-gradient(135deg, var(--accent), var(--info));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    margin-bottom: 0.25rem;
  }}
  .header {{
    margin-bottom: 2rem;
    padding-bottom: 1.5rem;
    border-bottom: 1px solid var(--border);
  }}
  .header-meta {{
    color: var(--text-dim);
    font-size: 0.85rem;
    margin-top: 0.5rem;
  }}
  .header-meta span {{ margin-right: 1.5rem; }}
  .summary {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: 1rem;
    margin-bottom: 2rem;
  }}
  .summary-card {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.25rem;
    text-align: center;
  }}
  .summary-card .number {{
    font-size: 2rem;
    font-weight: 700;
    font-family: var(--mono);
    line-height: 1.2;
  }}
  .summary-card .label {{
    font-size: 0.8rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--text-dim);
    margin-top: 0.25rem;
  }}
  .card-error .number {{ color: var(--error); }}
  .card-warning .number {{ color: var(--warning); }}
  .card-info .number {{ color: var(--info); }}
  .card-total .number {{ color: var(--text); }}
  .card-cost .number {{ color: var(--success); font-size: 1.5rem; }}
  .checker {{
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 12px;
    margin-bottom: 1rem;
    overflow: hidden;
  }}
  .checker-header {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 1rem 1.25rem;
    cursor: pointer;
    user-select: none;
    transition: background 0.15s;
  }}
  .checker-header:hover {{ background: var(--surface2); }}
  .checker-header h2 {{ font-size: 1rem; font-weight: 600; }}
  .checker-meta {{ font-size: 0.8rem; color: var(--text-dim); }}
  .checker-body {{ padding: 0 1.25rem 1.25rem; }}
  .checker.collapsed .checker-body {{ display: none; }}
  .badge {{
    display: inline-block;
    padding: 0.15em 0.6em;
    border-radius: 6px;
    font-size: 0.7rem;
    font-weight: 700;
    font-family: var(--mono);
    letter-spacing: 0.03em;
  }}
  .badge.error {{ background: var(--error-bg); color: var(--error); }}
  .badge.warning {{ background: var(--warning-bg); color: var(--warning); }}
  .badge.info {{ background: var(--info-bg); color: var(--info); }}
  .stat-error {{ color: var(--error); font-weight: 600; }}
  .stat-warning {{ color: var(--warning); font-weight: 600; }}
  .stat-info {{ color: var(--info); font-weight: 600; }}
  .findings-table {{
    width: 100%;
    border-collapse: separate;
    border-spacing: 0;
    font-size: 0.85rem;
  }}
  .findings-table thead th {{
    text-align: left;
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid var(--border);
    color: var(--text-dim);
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
  }}
  .findings-table tbody tr {{ transition: background 0.1s; }}
  .findings-table tbody tr:hover {{ background: var(--surface2); }}
  .findings-table td {{
    padding: 0.75rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .findings-table tbody tr:last-child td {{ border-bottom: none; }}
  .col-severity {{ width: 90px; }}
  .col-location {{ width: 200px; color: var(--text-dim); font-family: var(--mono); font-size: 0.8rem; }}
  .col-suggestion {{ color: var(--text-dim); }}
  .no-issues {{ color: var(--success); padding: 0.75rem 0; font-weight: 500; }}
  .footer {{
    margin-top: 2rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    text-align: center;
    color: var(--text-dim);
    font-size: 0.75rem;
  }}
  .footer a {{ color: var(--accent); text-decoration: none; }}
  .footer a:hover {{ text-decoration: underline; }}
  .cot-details {{ margin-top: 1rem; }}
  .cot-summary {{
    cursor: pointer;
    color: var(--text-dim);
    font-size: 0.8rem;
    font-weight: 600;
    padding: 0.5rem 0;
    user-select: none;
  }}
  .cot-summary:hover {{ color: var(--accent); }}
  .cot-body {{
    max-height: 500px;
    overflow-y: auto;
    padding: 0.75rem;
    background: var(--bg);
    border: 1px solid var(--border);
    border-radius: 8px;
    font-family: var(--mono);
    font-size: 0.75rem;
    line-height: 1.5;
  }}
  .cot-entry {{ padding: 0.3rem 0; border-bottom: 1px solid var(--border); }}
  .cot-entry:last-child {{ border-bottom: none; }}
  .cot-ts {{ color: var(--text-dim); }}
  .cot-tag {{
    display: inline-block;
    padding: 0.1em 0.4em;
    border-radius: 4px;
    font-size: 0.65rem;
    font-weight: 700;
    margin-right: 0.3em;
  }}
  .cot-request .cot-tag {{ background: rgba(124,110,240,0.15); color: var(--accent); }}
  .cot-response .cot-tag {{ background: rgba(94,181,247,0.15); color: var(--info); }}
  .cot-tool-result .cot-tag {{ background: rgba(74,222,128,0.15); color: var(--success); }}
  .cot-finding .cot-tag {{ background: var(--warning-bg); color: var(--warning); }}
  .cot-error .cot-tag {{ background: var(--error-bg); color: var(--error); }}
  .cot-text {{ color: var(--text-dim); margin: 0.25rem 0 0 1.5rem; white-space: pre-wrap; }}
  .cot-tool-call {{ color: var(--accent); margin: 0.25rem 0 0 1.5rem; }}
  .cot-preview {{ color: var(--text-dim); margin: 0.25rem 0 0 1.5rem; white-space: pre-wrap; }}
  .confidence-badge {{
    display: inline-block;
    padding: 0.1em 0.4em;
    border-radius: 4px;
    font-size: 0.6rem;
    font-weight: 700;
    font-family: var(--mono);
    margin-left: 0.3em;
    vertical-align: middle;
  }}
  .confidence-badge.confirmed {{ background: rgba(74,222,128,0.15); color: var(--success); }}
  .confidence-badge.downgraded {{ background: var(--warning-bg); color: var(--warning); }}
  @media (max-width: 768px) {{
    body {{ padding: 1rem; }}
    .summary {{ grid-template-columns: repeat(2, 1fr); }}
    .checker-header {{ flex-direction: column; align-items: flex-start; gap: 0.5rem; }}
    .findings-table {{ font-size: 0.8rem; }}
    .col-location {{ display: none; }}
  }}
</style>
</head>
<body>

<div class="header">
  <h1>{tr("report_title")}</h1>
  <div class="header-meta">
    <span>{tr("journal_label")}: <strong>{journal_html}</strong></span>
    <span>{tr("generated")}: {timestamp}</span>
    <span>Model: <strong>{_esc(report.model) or "N/A"}</strong></span>
  </div>
</div>

<div class="summary">
  <div class="summary-card card-error">
    <div class="number">{errors}</div>
    <div class="label">{tr("errors")}</div>
  </div>
  <div class="summary-card card-warning">
    <div class="number">{warnings}</div>
    <div class="label">{tr("warnings")}</div>
  </div>
  <div class="summary-card card-info">
    <div class="number">{infos}</div>
    <div class="label">{tr("info")}</div>
  </div>
  <div class="summary-card card-total">
    <div class="number">{total}</div>
    <div class="label">{tr("total")}</div>
  </div>
  <div class="summary-card card-cost">
    <div class="number">${report.total_cost:.2f}</div>
    <div class="label">{tr("est_cost")}</div>
  </div>
</div>

{"".join(checker_sections)}

<div class="footer">
  {tr("generated_by")} <a href="https://github.com/odafeng/sub-checker">sub-checker</a> · {_esc(report.model)} · {timestamp}
</div>

</body>
</html>"""
