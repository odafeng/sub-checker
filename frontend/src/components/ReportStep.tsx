import { useState } from "react";
import type { ReportData, Finding } from "../App";

interface Props {
  report: ReportData;
  reportHtml: string;
  lang: string;
}

const SEV_COLORS = {
  error: {
    bg: "bg-[var(--error)]/10",
    text: "text-[var(--error)]",
    border: "border-[var(--error)]/30",
    ring: "ring-[var(--error)]",
  },
  warning: {
    bg: "bg-[var(--warning)]/10",
    text: "text-[var(--warning)]",
    border: "border-[var(--warning)]/30",
    ring: "ring-[var(--warning)]",
  },
  info: {
    bg: "bg-[var(--info)]/10",
    text: "text-[var(--info)]",
    border: "border-[var(--info)]/30",
    ring: "ring-[var(--info)]",
  },
};

type Severity = keyof typeof SEV_COLORS;

const FOCUS_RING =
  "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]";

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path
        d="M8 2v8m0 0L5 7m3 3l3-3M3 13h10"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

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
      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-bold font-mono bg-[var(--success)]/15 text-[var(--success)] ml-1.5">
        {Math.round(confidence * 100)}%
      </span>
    );
  }
  if (status === "downgraded") {
    return (
      <span className="inline-block px-1.5 py-0.5 rounded text-[11px] font-bold font-mono bg-[var(--warning)]/15 text-[var(--warning)] ml-1.5">
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
            <p className="text-xs text-[var(--text-dim)] font-mono mt-1">
              <span className="font-sans uppercase tracking-wide mr-1">Loc</span>
              {f.location}
            </p>
          )}
          {f.context && (
            <p className="text-xs text-[var(--text-dim)] font-mono mt-1.5 pl-3 border-l-2 border-[var(--border)] line-clamp-2">
              {f.context}
            </p>
          )}
          {f.suggestion && (
            <p className="text-xs text-[var(--accent)] mt-1.5 border-l-2 border-[var(--accent)]/40 pl-2">
              {zh ? "建議" : "Suggestion"}: {f.suggestion}
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
  const [sevFilter, setSevFilter] = useState<Severity | null>(null);
  const zh = lang === "zh-TW";

  const toggle = (name: string) => {
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  // Filter out filtered findings (and apply the severity filter) for card view
  const filteredResults = report.results
    .map((r) => ({
      ...r,
      findings: r.findings.filter(
        (f) =>
          f.validation_status !== "filtered" &&
          (!sevFilter || f.severity === sevFilter)
      ),
    }))
    .filter((r) => !sevFilter || r.findings.length > 0);

  return (
    <div className="space-y-6">
      {/* Model info */}
      {report.model && (
        <div className="text-xs text-[var(--text-dim)] text-right">
          Model: <span className="font-mono font-medium text-[var(--text)]">{report.model}</span>
        </div>
      )}

      {/* Summary cards — severity cards toggle filtering the findings list */}
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-5 gap-3">
        {(
          [
            { sev: "error" as const, n: report.summary.error, label: zh ? "錯誤" : "Errors" },
            { sev: "warning" as const, n: report.summary.warning, label: zh ? "警告" : "Warnings" },
            { sev: "info" as const, n: report.summary.info, label: zh ? "資訊" : "Info" },
          ]
        ).map((c) => (
          <button
            key={c.label}
            type="button"
            onClick={() => setSevFilter((prev) => (prev === c.sev ? null : c.sev))}
            aria-pressed={sevFilter === c.sev}
            className={`bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 text-center cursor-pointer transition-colors hover:bg-[var(--surface2)] ${FOCUS_RING} ${
              sevFilter === c.sev ? `ring-2 ${SEV_COLORS[c.sev].ring}` : ""
            }`}
          >
            <div className={`text-2xl font-bold font-mono ${SEV_COLORS[c.sev].text}`}>
              {c.n}
            </div>
            <div className="text-xs text-[var(--text-dim)] uppercase mt-1">
              {c.label}
            </div>
          </button>
        ))}
        {[
          {
            n: report.summary.error + report.summary.warning + report.summary.info,
            label: zh ? "合計" : "Total",
            cls: "text-[var(--text)]",
          },
          { n: `$${report.total_cost.toFixed(2)}`, label: zh ? "費用" : "Cost", cls: "text-[var(--text-dim)]" },
        ].map((c) => (
          <div
            key={c.label}
            className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 text-center"
          >
            <div className={`text-2xl font-bold font-mono ${c.cls}`}>
              {c.n}
            </div>
            <div className="text-xs text-[var(--text-dim)] uppercase mt-1">
              {c.label}
            </div>
          </div>
        ))}
      </div>

      {/* View toggle */}
      <div className="flex items-center gap-2">
        <div className="inline-flex rounded-lg bg-[var(--surface)] p-0.5 border border-[var(--border)]">
          <button
            onClick={() => setView("cards")}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${FOCUS_RING} ${
              view === "cards"
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--text-dim)] hover:bg-[var(--surface2)] hover:text-[var(--text)]"
            }`}
          >
            {zh ? "卡片檢視" : "Card View"}
          </button>
          <button
            onClick={() => setView("html")}
            className={`px-4 py-1.5 rounded-md text-sm font-medium transition-colors ${FOCUS_RING} ${
              view === "html"
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--text-dim)] hover:bg-[var(--surface2)] hover:text-[var(--text)]"
            }`}
          >
            {zh ? "HTML 報告" : "HTML Report"}
          </button>
        </div>
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
          className={`ml-auto inline-flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-medium bg-[var(--surface)] text-[var(--accent)] hover:bg-[var(--surface2)] transition-colors ${FOCUS_RING}`}
        >
          <DownloadIcon /> {zh ? "下載 HTML" : "Download HTML"}
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
                className={`w-full flex items-center justify-between p-4 hover:bg-[var(--surface2)] transition-colors ${FOCUS_RING}`}
              >
                <h3 className="font-semibold">
                  {r.display_name ?? r.checker}
                </h3>
                <div className="flex items-center gap-3 text-sm text-[var(--text-dim)]">
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
