import { useState } from "react";
import type { ReportData, Finding } from "../App";

interface Props {
  report: ReportData;
  reportHtml: string;
  lang: string;
}

const SEV_COLORS = {
  error: { bg: "bg-red-500/10", text: "text-red-400", border: "border-red-500/30" },
  warning: { bg: "bg-amber-500/10", text: "text-amber-400", border: "border-amber-500/30" },
  info: { bg: "bg-blue-500/10", text: "text-blue-400", border: "border-blue-500/30" },
};

const SEV_LABEL = {
  error: { en: "ERROR", zh: "錯誤" },
  warning: { en: "WARNING", zh: "警告" },
  info: { en: "INFO", zh: "資訊" },
};

function Badge({ severity, lang }: { severity: string; lang: string }) {
  const s = SEV_COLORS[severity as keyof typeof SEV_COLORS] ?? SEV_COLORS.info;
  const label =
    SEV_LABEL[severity as keyof typeof SEV_LABEL]?.[
      lang === "zh-TW" ? "zh" : "en"
    ] ?? severity;
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-bold font-mono ${s.bg} ${s.text}`}
    >
      {label}
    </span>
  );
}

function ConfidenceBadge({ status, confidence }: { status: string; confidence: number }) {
  if (status === "confirmed") {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold font-mono bg-emerald-500/15 text-emerald-400 ml-1.5">
        {Math.round(confidence * 100)}%
      </span>
    );
  }
  if (status === "downgraded") {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold font-mono bg-amber-500/15 text-amber-400 ml-1.5">
        {Math.round(confidence * 100)}%
      </span>
    );
  }
  return null;
}

function FindingRow({ f, lang }: { f: Finding; lang: string }) {
  const zh = lang === "zh-TW";
  return (
    <div className="border-b border-[var(--border)] last:border-0 py-3 px-1">
      <div className="flex items-start gap-3">
        <div className="flex items-center">
          <Badge severity={f.severity} lang={lang} />
          <ConfidenceBadge status={f.validation_status} confidence={f.confidence} />
        </div>
        <div className="flex-1 min-w-0">
          <p className="text-sm">{f.message}</p>
          {f.location && (
            <p className="text-xs text-[#8b90a5] font-mono mt-1">
              📍 {f.location}
            </p>
          )}
          {f.suggestion && (
            <p className="text-xs text-[var(--accent)] mt-1">
              💡 {zh ? "建議" : "Suggestion"}: {f.suggestion}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function ReportStep({ report, reportHtml, lang }: Props) {
  const [view, setView] = useState<"cards" | "html">("cards");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const zh = lang === "zh-TW";

  const toggle = (name: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // Filter out filtered findings from all results for card view
  const filteredResults = report.results.map((r) => ({
    ...r,
    findings: r.findings.filter((f) => f.validation_status !== "filtered"),
  }));

  return (
    <div className="space-y-6">
      {/* Model info */}
      {report.model && (
        <div className="text-xs text-[#8b90a5] text-right">
          Model: <span className="font-mono font-medium text-[var(--text)]">{report.model}</span>
        </div>
      )}

      {/* Summary cards */}
      <div className="grid grid-cols-5 gap-3">
        {[
          { n: report.summary.error, label: zh ? "錯誤" : "Errors", cls: "text-[var(--error)]" },
          { n: report.summary.warning, label: zh ? "警告" : "Warnings", cls: "text-[var(--warning)]" },
          { n: report.summary.info, label: zh ? "資訊" : "Info", cls: "text-[var(--info)]" },
          {
            n: report.summary.error + report.summary.warning + report.summary.info,
            label: zh ? "合計" : "Total",
            cls: "text-white",
          },
          { n: `$${report.total_cost.toFixed(2)}`, label: zh ? "費用" : "Cost", cls: "text-[var(--success)]" },
        ].map((c) => (
          <div
            key={c.label}
            className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 text-center"
          >
            <div className={`text-2xl font-bold font-mono ${c.cls}`}>
              {c.n}
            </div>
            <div className="text-xs text-[#8b90a5] uppercase mt-1">
              {c.label}
            </div>
          </div>
        ))}
      </div>

      {/* View toggle */}
      <div className="flex gap-2">
        <button
          onClick={() => setView("cards")}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            view === "cards"
              ? "bg-[var(--accent)] text-white"
              : "bg-[var(--surface)] text-[#8b90a5]"
          }`}
        >
          {zh ? "卡片檢視" : "Card View"}
        </button>
        <button
          onClick={() => setView("html")}
          className={`px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
            view === "html"
              ? "bg-[var(--accent)] text-white"
              : "bg-[var(--surface)] text-[#8b90a5]"
          }`}
        >
          {zh ? "HTML 報告" : "HTML Report"}
        </button>
        <button
          onClick={() => {
            const blob = new Blob([reportHtml], { type: "text/html" });
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "sub-check-report.html";
            a.click();
            URL.revokeObjectURL(url);
          }}
          className="ml-auto px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--surface)] text-[var(--accent)] hover:bg-[var(--surface2)] transition-colors"
        >
          ⬇ {zh ? "下載 HTML" : "Download HTML"}
        </button>
      </div>

      {/* Content */}
      {view === "cards" ? (
        <div className="space-y-3">
          {filteredResults.map((r) => (
            <div
              key={r.checker}
              className="bg-[var(--surface)] border border-[var(--border)] rounded-xl overflow-hidden"
            >
              <button
                onClick={() => toggle(r.checker)}
                className="w-full flex items-center justify-between p-4 hover:bg-[var(--surface2)] transition-colors"
              >
                <h3 className="font-semibold">
                  {r.display_name ?? r.checker}
                </h3>
                <div className="flex items-center gap-3 text-sm text-[#8b90a5]">
                  {r.findings.filter((f) => f.severity === "error").length >
                    0 && (
                    <span className="text-[var(--error)]">
                      {r.findings.filter((f) => f.severity === "error").length}{" "}
                      {zh ? "錯誤" : "errors"}
                    </span>
                  )}
                  {r.findings.filter((f) => f.severity === "warning").length >
                    0 && (
                    <span className="text-[var(--warning)]">
                      {
                        r.findings.filter((f) => f.severity === "warning")
                          .length
                      }{" "}
                      {zh ? "警告" : "warnings"}
                    </span>
                  )}
                  <span>{r.elapsed_seconds.toFixed(1)}s</span>
                  <span>{collapsed.has(r.checker) ? "▸" : "▾"}</span>
                </div>
              </button>
              {!collapsed.has(r.checker) && (
                <div className="px-4 pb-4">
                  {r.findings.length === 0 ? (
                    <p className="text-[var(--success)] text-sm py-2">
                      {zh ? "未發現問題" : "No issues found"}
                    </p>
                  ) : (
                    r.findings.map((f, i) => (
                      <FindingRow key={`${r.checker}-${i}`} f={f} lang={lang} />
                    ))
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      ) : (
        <iframe
          srcDoc={reportHtml}
          // Fully sandboxed: report HTML must not run scripts or reach the parent page
          sandbox=""
          className="w-full rounded-xl border border-[var(--border)]"
          style={{ height: "80vh" }}
          title="HTML Report"
        />
      )}
    </div>
  );
}
