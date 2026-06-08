import { useState } from "react";
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
  phase?: number;
  agents?: string[];
}

export default function App() {
  const [step, setStep] = useState<Step>("upload");
  const [manuscript, setManuscript] = useState<ManuscriptInfo | null>(null);
  const [report, setReport] = useState<ReportData | null>(null);
  const [reportHtml, setReportHtml] = useState("");
  const [progress, setProgress] = useState<AgentProgress[]>([]);
  const [lang, setLang] = useState<"en" | "zh-TW">("en");

  const onUploaded = (info: ManuscriptInfo) => {
    setManuscript(info);
    setStep("config");
  };

  const onStartCheck = (journal: string, checkers: string[]) => {
    if (!manuscript) return;
    setStep("running");
    setProgress([]);

    const wsUrl = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws/check/${manuscript.session_id}`;
    const ws = new WebSocket(wsUrl);

    ws.onopen = () => {
      ws.send(JSON.stringify({ journal, checkers, lang }));
    };

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (msg.type === "report") {
        setReport(msg.data);
        setReportHtml(msg.html);
        setStep("report");
        ws.close();
      } else {
        setProgress((prev) => [...prev, msg]);
      }
    };

    ws.onerror = () => {
      setProgress((prev) => [
        ...prev,
        { type: "error", error: "WebSocket connection failed" },
      ]);
    };
  };

  const onReset = () => {
    setStep("upload");
    setManuscript(null);
    setReport(null);
    setReportHtml("");
    setProgress([]);
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
            className="bg-[var(--surface)] border border-[var(--border)] rounded-lg px-3 py-1.5 text-sm"
          >
            <option value="en">English</option>
            <option value="zh-TW">繁體中文</option>
          </select>
          {step !== "upload" && (
            <button
              onClick={onReset}
              className="text-sm text-[var(--accent)] hover:underline"
            >
              {lang === "zh-TW" ? "重新開始" : "Start Over"}
            </button>
          )}
        </div>
      </header>

      {/* Steps */}
      {step === "upload" && <UploadStep onUploaded={onUploaded} lang={lang} />}
      {step === "config" && manuscript && (
        <ConfigStep
          manuscript={manuscript}
          onStart={onStartCheck}
          lang={lang}
        />
      )}
      {step === "running" && <RunningStep progress={progress} lang={lang} />}
      {step === "report" && report && (
        <ReportStep report={report} reportHtml={reportHtml} lang={lang} />
      )}
    </div>
  );
}
