import { useEffect, useRef, useState } from "react";
import UploadStep from "./components/UploadStep";
import ConfigStep from "./components/ConfigStep";
import RunningStep from "./components/RunningStep";
import ReportStep from "./components/ReportStep";

export type Step = "upload" | "config" | "running" | "report";

export interface ManuscriptInfo {
  session_id: string;
  filename: string;
  title: string;
  sections: string[];
  word_count: number;
  paragraph_count: number;
  has_references: boolean;
}

export interface Finding {
  severity: "error" | "warning" | "info";
  message: string;
  location: string | null;
  suggestion: string | null;
  context: string | null;
  confidence: number;
  validation_status: "" | "confirmed" | "downgraded" | "filtered";
}

export interface CheckerResult {
  checker: string;
  display_name?: string;
  elapsed_seconds: number;
  findings: Finding[];
}

export interface ReportData {
  manuscript_path: string;
  timestamp: string;
  target_journal: string | null;
  model: string;
  total_cost: number;
  summary: { error: number; warning: number; info: number };
  results: CheckerResult[];
}

export interface AgentProgress {
  type: string;
  agent?: string;
  findings_count?: number;
  elapsed?: number;
  error?: string;
  message?: string;
  total_agents?: number;
}

// Skip duplicate per-agent lifecycle events (e.g. from network retries)
function appendProgress(prev: AgentProgress[], msg: AgentProgress): AgentProgress[] {
  const perAgentEvents = ["agent_start", "agent_done", "agent_error"];
  if (
    perAgentEvents.includes(msg.type) &&
    prev.some((p) => p.type === msg.type && p.agent === msg.agent)
  ) {
    return prev;
  }
  return [...prev, msg];
}

const STEP_ORDER: Step[] = ["upload", "config", "running", "report"];

const STEP_LABELS: Record<Step, { en: string; zh: string }> = {
  upload: { en: "Upload", zh: "上傳" },
  config: { en: "Config", zh: "設定" },
  running: { en: "Running", zh: "檢查中" },
  report: { en: "Report", zh: "報告" },
};

function Stepper({ step, lang }: { step: Step; lang: string }) {
  const zh = lang === "zh-TW";
  const current = STEP_ORDER.indexOf(step);
  return (
    <nav
      aria-label={zh ? "進度" : "Progress"}
      className="flex items-center justify-center mb-8"
    >
      {STEP_ORDER.map((s, i) => (
        <div key={s} className="flex items-center">
          {i > 0 && <div className="w-8 sm:w-12 h-px bg-[var(--border)] mx-2" />}
          <div className="flex items-center gap-2">
            <span
              aria-current={i === current ? "step" : undefined}
              className={`flex items-center justify-center w-6 h-6 rounded-full text-xs font-semibold ${
                i < current
                  ? "bg-[var(--accent)]/20 text-[var(--accent)]"
                  : i === current
                  ? "bg-[var(--accent)] text-white"
                  : "bg-[var(--surface2)] text-[var(--text-dim)]"
              }`}
            >
              {i < current ? "✓" : i + 1}
            </span>
            <span
              className={`hidden sm:inline text-xs ${
                i === current
                  ? "text-[var(--text)] font-medium"
                  : "text-[var(--text-dim)]"
              }`}
            >
              {zh ? STEP_LABELS[s].zh : STEP_LABELS[s].en}
            </span>
          </div>
        </div>
      ))}
    </nav>
  );
}

export default function App() {
  const [step, setStep] = useState<Step>("upload");
  const [manuscript, setManuscript] = useState<ManuscriptInfo | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [reportHtml, setReportHtml] = useState("");
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  const [totalAgents, setTotalAgents] = useState<number | null>(null);
  const [lang, setLang] = useState<"en" | "zh-TW">("en");
  const wsRef = useRef<WebSocket | null>(null);

  const closeWs = () => {
    if (wsRef.current) {
      wsRef.current.onclose = null;
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  // Close any open WebSocket when the component unmounts
  useEffect(() => closeWs, []);

  const onUploaded = (info: ManuscriptInfo) => {
    setManuscript(info);
    setStep("config");
  };

  const onStartCheck = (journal: string, checkers: string[]) => {
    if (!manuscript) return;
    setStep("running");
    setProgress([]);
    setTotalAgents(null);
    closeWs();

    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/check/${manuscript.session_id}`;
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;

    ws.onopen = () => {
      ws.send(JSON.stringify({ journal, checkers, lang }));
    };

    ws.onmessage = (e) => {
      let msg: AgentProgress & { data?: ReportData; html?: string };
      try {
        msg = JSON.parse(e.data);
      } catch {
        setProgress((prev) =>
          appendProgress(prev, { type: "error", error: "Received malformed message" })
        );
        return;
      }
      if (msg.type === "report" && msg.data) {
        setReport(msg.data);
        setReportHtml(msg.html ?? "");
        setStep("report");
        closeWs();
      } else {
        if (msg.type === "run_start" && typeof msg.total_agents === "number") {
          setTotalAgents(msg.total_agents);
        }
        setProgress((prev) => appendProgress(prev, msg));
      }
    };

    // onerror and onclose both fire on a single failed connection; the flag
    // keeps that from producing two stacked error banners.
    let hadError = false;
    ws.onerror = () => {
      hadError = true;
      setProgress((prev) =>
        appendProgress(prev, { type: "error", error: "WebSocket connection failed" })
      );
    };

    // Fires when the connection drops before a report arrives (server
    // restart, network loss) — onclose is nulled on intentional close.
    ws.onclose = () => {
      wsRef.current = null;
      if (hadError) return;
      setProgress((prev) =>
        appendProgress(prev, {
          type: "error",
          error: "Connection closed before the check finished",
        })
      );
    };
  };

  const onReset = () => {
    closeWs();
    setStep("upload");
    setManuscript(null);
    setReport(null);
    setReportHtml("");
    setProgress([]);
    setTotalAgents(null);
  };

  return (
    <div className="min-h-screen p-6 max-w-5xl mx-auto">
      {/* Header */}
      <header className="flex items-center justify-between mb-8">
        <h1
          className="text-2xl font-bold"
          style={{
            background: "linear-gradient(135deg, var(--accent), var(--info))",
            WebkitBackgroundClip: "text",
            WebkitTextFillColor: "transparent",
          }}
        >
          Sub-Checker
        </h1>
        <div className="flex items-center gap-3">
          <select
            value={lang}
            onChange={(e) => setLang(e.target.value as "en" | "zh-TW")}
            className="bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-sm focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
          >
            <option value="en">English</option>
            <option value="zh-TW">繁體中文</option>
          </select>
          {step !== "upload" && (
            <button
              onClick={onReset}
              className="text-sm text-[var(--accent)] hover:underline rounded focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
            >
              {lang === "zh-TW" ? "重新開始" : "Start Over"}
            </button>
          )}
        </div>
      </header>

      {/* Wizard stepper */}
      <Stepper step={step} lang={lang} />

      {/* Steps */}
      {step === "upload" && <UploadStep onUploaded={onUploaded} lang={lang} />}
      {step === "config" && manuscript && (
        <ConfigStep
          manuscript={manuscript}
          onStart={onStartCheck}
          lang={lang}
        />
      )}
      {step === "running" && (
        <RunningStep progress={progress} totalAgents={totalAgents} lang={lang} />
      )}
      {step === "report" && report && (
        <ReportStep report={report} reportHtml={reportHtml} lang={lang} />
      )}
    </div>
  );
}
