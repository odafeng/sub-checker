import { useEffect, useState } from "react";
import type { AgentProgress } from "../App";

const CHECKERS = [
  { name: "typo_grammar", en: "Typo & Grammar", zh: "拼字與文法", icon: "Aa", color: "#7c6ef0" },
  { name: "figure_table", en: "Figure & Table", zh: "圖表檢查", icon: "□▪", color: "#5eb5f7" },
  { name: "citation_exist", en: "Citation Existence", zh: "引用完整性", icon: "「」", color: "#f0a73a" },
  { name: "citation_format", en: "Citation Format", zh: "引用格式", icon: "§", color: "#4ade80" },
  { name: "journal_guidelines", en: "Journal Guidelines", zh: "期刊投稿規範", icon: "📋", color: "#f472b6" },
  { name: "logic", en: "Logic Consistency", zh: "邏輯一致性", icon: "⟷", color: "#c084fc" },
  { name: "citation_claim", en: "Citation-Claim", zh: "引用-主張驗證", icon: "✓?", color: "#fb923c" },
];

interface Props {
  progress: AgentProgress[];
  lang: string;
}

function Spinner({ color }: { color: string }) {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" className="animate-spin">
      <circle cx="12" cy="12" r="10" fill="none" stroke={color} strokeWidth="2.5" strokeOpacity="0.2" />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        fill="none"
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function CheckIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" fill="var(--success)" fillOpacity="0.15" />
      <path d="M8 12.5l2.5 2.5 5.5-5.5" stroke="var(--success)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

function ErrorIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" fill="var(--error)" fillOpacity="0.15" />
      <path d="M15 9l-6 6M9 9l6 6" stroke="var(--error)" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function ElapsedTimer() {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.floor((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  return <span className="font-mono text-xs tabular-nums">{m}:{s.toString().padStart(2, "0")}</span>;
}

export default function RunningStep({ progress, lang }: Props) {
  const zh = lang === "zh-TW";
  const started = new Set<string>();
  const done = new Map<string, { findings: number; elapsed: number }>();
  const errors = new Map<string, string>();

  for (const p of progress) {
    if (p.type === "agent_start" && p.agent) started.add(p.agent);
    if (p.type === "agent_done" && p.agent)
      done.set(p.agent, { findings: p.findings_count ?? 0, elapsed: p.elapsed ?? 0 });
    if (p.type === "agent_error" && p.agent)
      errors.set(p.agent, p.error ?? "Unknown error");
  }

  const activeCheckers = CHECKERS.filter((c) => started.has(c.name));
  const doneCount = done.size + errors.size;
  const totalCount = started.size;
  const pct = totalCount > 0 ? Math.round((doneCount / totalCount) * 100) : 0;

  return (
    <div className="space-y-8">
      {/* Header with overall progress */}
      <div className="text-center space-y-4">
        <div className="relative inline-flex items-center justify-center">
          {/* Animated ring */}
          <svg width="120" height="120" viewBox="0 0 120 120" className="transform -rotate-90">
            <circle cx="60" cy="60" r="52" fill="none" stroke="var(--border)" strokeWidth="6" />
            <circle
              cx="60" cy="60" r="52"
              fill="none"
              stroke="var(--accent)"
              strokeWidth="6"
              strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 52}`}
              strokeDashoffset={`${2 * Math.PI * 52 * (1 - pct / 100)}`}
              style={{ transition: "stroke-dashoffset 0.5s ease" }}
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-2xl font-bold font-mono">{pct}%</span>
            <ElapsedTimer />
          </div>
        </div>
        <div>
          <h2 className="text-xl font-semibold">
            {zh ? "AI 正在審查你的文稿" : "AI is reviewing your manuscript"}
          </h2>
          <p className="text-sm text-[#8b90a5] mt-1">
            {doneCount}/{totalCount} {zh ? "項檢查完成" : "checks completed"}
          </p>
        </div>
      </div>

      {/* Agent cards */}
      <div className="grid gap-3">
        {activeCheckers.map((checker) => {
          const isDone = done.has(checker.name);
          const isError = errors.has(checker.name);
          const isRunning = !isDone && !isError;
          const info = done.get(checker.name);

          return (
            <div
              key={checker.name}
              className="relative overflow-hidden rounded-2xl transition-all duration-500"
              style={{
                background: isRunning
                  ? `linear-gradient(135deg, ${checker.color}08, ${checker.color}15)`
                  : "var(--surface)",
                border: `1px solid ${isRunning ? checker.color + "40" : "var(--border)"}`,
                boxShadow: isRunning ? `0 0 30px ${checker.color}10` : "none",
              }}
            >
              {/* Running shimmer effect */}
              {isRunning && (
                <div
                  className="absolute inset-0 opacity-[0.07]"
                  style={{
                    background: `linear-gradient(90deg, transparent, ${checker.color}, transparent)`,
                    animation: "shimmer 2s ease-in-out infinite",
                  }}
                />
              )}

              <div className="relative flex items-center gap-4 p-4">
                {/* Status icon */}
                <div className="flex-shrink-0">
                  {isError ? (
                    <ErrorIcon />
                  ) : isDone ? (
                    <CheckIcon />
                  ) : (
                    <Spinner color={checker.color} />
                  )}
                </div>

                {/* Name + icon badge */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span
                      className="inline-flex items-center justify-center w-7 h-7 rounded-lg text-xs font-bold"
                      style={{ background: checker.color + "20", color: checker.color }}
                    >
                      {checker.icon}
                    </span>
                    <span className="font-medium">
                      {zh ? checker.zh : checker.en}
                    </span>
                  </div>
                </div>

                {/* Status text */}
                <div className="flex-shrink-0 text-right">
                  {isError ? (
                    <span className="text-sm text-[var(--error)] font-medium">
                      {zh ? "失敗" : "Failed"}
                    </span>
                  ) : isDone && info ? (
                    <div className="text-right">
                      <div className="text-sm font-medium">
                        {info.findings > 0 ? (
                          <span style={{ color: checker.color }}>
                            {info.findings} {zh ? "個發現" : "findings"}
                          </span>
                        ) : (
                          <span className="text-[var(--success)]">
                            {zh ? "通過" : "Passed"}
                          </span>
                        )}
                      </div>
                      <div className="text-xs text-[#8b90a5] font-mono">
                        {info.elapsed}s
                      </div>
                    </div>
                  ) : (
                    <span
                      className="text-sm font-medium animate-pulse"
                      style={{ color: checker.color }}
                    >
                      {zh ? "分析中..." : "Analyzing..."}
                    </span>
                  )}
                </div>
              </div>

              {/* Progress bar for running agents */}
              {isRunning && (
                <div className="h-0.5 bg-[var(--border)]">
                  <div
                    className="h-full rounded-full"
                    style={{
                      background: checker.color,
                      animation: "indeterminate 1.5s ease-in-out infinite",
                    }}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Connecting state */}
      {started.size === 0 && (
        <div className="flex flex-col items-center gap-4 py-16">
          <Spinner color="var(--accent)" />
          <p className="text-[#8b90a5]">
            {zh ? "正在連線至 AI 引擎..." : "Connecting to AI engine..."}
          </p>
        </div>
      )}

      {/* Animations */}
      <style>{`
        @keyframes shimmer {
          0%, 100% { transform: translateX(-100%); }
          50% { transform: translateX(100%); }
        }
        @keyframes indeterminate {
          0% { width: 0%; margin-left: 0%; }
          50% { width: 40%; margin-left: 30%; }
          100% { width: 0%; margin-left: 100%; }
        }
      `}</style>
    </div>
  );
}
