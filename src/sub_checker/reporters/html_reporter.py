"""HTML reporter with styled output."""

from __future__ import annotations

import html

from sub_checker.models import Report, Severity

_SEVERITY_BADGE = {
    Severity.ERROR: '<span class="badge error">ERROR</span>',
    Severity.WARNING: '<span class="badge warning">WARNING</span>',
    Severity.INFO: '<span class="badge info">INFO</span>',
}

_SEVERITY_ORDER = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}


def _esc(text: str | None) -> str:
    if not text:
        return "—"
    return html.escape(text)


def format_html(report: Report) -> str:
    errors = report.summary.get(Severity.ERROR, 0)
    warnings = report.summary.get(Severity.WARNING, 0)
    infos = report.summary.get(Severity.INFO, 0)
    total = errors + warnings + infos

    # Build checker sections
    checker_sections = []
    for result in report.results:
        findings_html = ""
        if not result.findings:
            findings_html = '<p class="no-issues">No issues found.</p>'
        else:
            sorted_findings = sorted(result.findings, key=lambda f: _SEVERITY_ORDER[f.severity])
            rows = []
            for f in sorted_findings:
                rows.append(
                    f"<tr>"
                    f'<td class="col-severity">{_SEVERITY_BADGE[f.severity]}</td>'
                    f'<td class="col-location">{_esc(f.location)}</td>'
                    f'<td class="col-message">{_esc(f.message)}</td>'
                    f'<td class="col-suggestion">{_esc(f.suggestion)}</td>'
                    f"</tr>"
                )
            findings_html = (
                '<table class="findings-table">'
                "<thead><tr>"
                "<th>Severity</th><th>Location</th><th>Message</th><th>Suggestion</th>"
                "</tr></thead>"
                f"<tbody>{''.join(rows)}</tbody>"
                "</table>"
            )

        e = sum(1 for f in result.findings if f.severity == Severity.ERROR)
        w = sum(1 for f in result.findings if f.severity == Severity.WARNING)
        i = sum(1 for f in result.findings if f.severity == Severity.INFO)
        stats = []
        if e:
            stats.append(f'<span class="stat-error">{e} error{"s" if e > 1 else ""}</span>')
        if w:
            stats.append(f'<span class="stat-warning">{w} warning{"s" if w > 1 else ""}</span>')
        if i:
            stats.append(f'<span class="stat-info">{i} info</span>')
        stats_html = " · ".join(stats) if stats else '<span class="stat-info">clean</span>'

        checker_sections.append(
            f'<section class="checker">'
            f'<div class="checker-header" onclick="this.parentElement.classList.toggle(\'collapsed\')">'
            f"<h2>{_esc(result.checker_name)}</h2>"
            f'<div class="checker-meta">{stats_html} · {result.elapsed_seconds:.1f}s</div>'
            f"</div>"
            f'<div class="checker-body">{findings_html}</div>'
            f"</section>"
        )

    journal_html = _esc(report.target_journal) if report.target_journal else "Not specified"
    timestamp = report.timestamp.strftime("%Y-%m-%d %H:%M UTC")

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Sub-Checker Report</title>
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

  /* Summary cards */
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

  /* Checker sections */
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
  .checker-header h2 {{
    font-size: 1rem;
    font-weight: 600;
    font-family: var(--mono);
  }}
  .checker-meta {{
    font-size: 0.8rem;
    color: var(--text-dim);
  }}
  .checker-body {{
    padding: 0 1.25rem 1.25rem;
    transition: max-height 0.3s ease;
  }}
  .checker.collapsed .checker-body {{
    display: none;
  }}

  /* Badges */
  .badge {{
    display: inline-block;
    padding: 0.15em 0.6em;
    border-radius: 6px;
    font-size: 0.7rem;
    font-weight: 700;
    font-family: var(--mono);
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }}
  .badge.error {{ background: var(--error-bg); color: var(--error); }}
  .badge.warning {{ background: var(--warning-bg); color: var(--warning); }}
  .badge.info {{ background: var(--info-bg); color: var(--info); }}

  .stat-error {{ color: var(--error); font-weight: 600; }}
  .stat-warning {{ color: var(--warning); font-weight: 600; }}
  .stat-info {{ color: var(--info); font-weight: 600; }}

  /* Table */
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
  .findings-table tbody tr {{
    transition: background 0.1s;
  }}
  .findings-table tbody tr:hover {{
    background: var(--surface2);
  }}
  .findings-table td {{
    padding: 0.75rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }}
  .findings-table tbody tr:last-child td {{
    border-bottom: none;
  }}
  .col-severity {{ width: 90px; }}
  .col-location {{ width: 200px; color: var(--text-dim); font-family: var(--mono); font-size: 0.8rem; }}
  .col-suggestion {{ color: var(--text-dim); }}

  .no-issues {{
    color: var(--success);
    padding: 0.75rem 0;
    font-weight: 500;
  }}

  /* Footer */
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
  <h1>Sub-Checker Report</h1>
  <div class="header-meta">
    <span>Journal: <strong>{journal_html}</strong></span>
    <span>Generated: {timestamp}</span>
  </div>
</div>

<div class="summary">
  <div class="summary-card card-error">
    <div class="number">{errors}</div>
    <div class="label">Errors</div>
  </div>
  <div class="summary-card card-warning">
    <div class="number">{warnings}</div>
    <div class="label">Warnings</div>
  </div>
  <div class="summary-card card-info">
    <div class="number">{infos}</div>
    <div class="label">Info</div>
  </div>
  <div class="summary-card card-total">
    <div class="number">{total}</div>
    <div class="label">Total</div>
  </div>
  <div class="summary-card card-cost">
    <div class="number">${report.total_cost:.2f}</div>
    <div class="label">Est. Cost</div>
  </div>
</div>

{"".join(checker_sections)}

<div class="footer">
  Generated by <a href="https://github.com/odafeng/sub-checker">sub-checker</a> · {timestamp}
</div>

</body>
</html>"""
