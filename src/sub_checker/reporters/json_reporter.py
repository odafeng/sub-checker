"""JSON reporter."""

from __future__ import annotations

import json
from typing import Any

from sub_checker.models import Report


def format_json(report: Report) -> str:
    data: dict[str, Any] = {
        "manuscript_path": report.manuscript_path,
        "timestamp": report.timestamp.isoformat(),
        "target_journal": report.target_journal,
        "model": report.model,
        "total_cost": report.total_cost,
        "summary": {s.value: c for s, c in report.summary.items()},
        "results": [],
    }

    for r in report.results:
        # Only include non-filtered findings
        active_findings = [f for f in r.findings if f.validation_status != "filtered"]
        result_data: dict[str, Any] = {
            "checker": r.checker_name,
            "elapsed_seconds": r.elapsed_seconds,
            "token_usage": {
                "input_tokens": r.token_usage.input_tokens,
                "output_tokens": r.token_usage.output_tokens,
                "cache_creation_input_tokens": r.token_usage.cache_creation_input_tokens,
                "cache_read_input_tokens": r.token_usage.cache_read_input_tokens,
            },
            "findings": [
                {
                    "severity": f.severity.value,
                    "message": f.message,
                    "location": f.location,
                    "suggestion": f.suggestion,
                    "context": f.context,
                    "confidence": f.confidence,
                    "validation_status": f.validation_status,
                }
                for f in active_findings
            ],
        }
        data["results"].append(result_data)

    return json.dumps(data, indent=2, ensure_ascii=False)
