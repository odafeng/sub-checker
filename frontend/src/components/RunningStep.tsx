import type { AgentProgress } from "../App";

const CHECKER_LABELS: Record<string, { en: string; zh: string }> = {
  typo_grammar: { en: "Typo & Grammar", zh: "拼字與文法" },
  figure_table: { en: "Figure & Table", zh: "圖表檢查" },
  citation_exist: { en: "Citation Existence", zh: "引用完整性" },
  citation_format: { en: "Citation Format", zh: "引用格式" },
  journal_guidelines: { en: "Journal Guidelines", zh: "期刊投稿規範" },
  logic: { en: "Logic Consistency", zh: "邏輯一致性" },
  citation_claim: { en: "Citation-Claim", zh: "引用-主張驗證" },
};

interface Props {
  progress: AgentProgress[];
  lang: string;
}

export default function RunningStep({ progress, lang }: Props) {
  const zh = lang === "zh-TW";
  const started = new Set<string>();
  const done = new Map<string, { findings: number; elapsed: number }>();
  const errors = new Map<string, string>();

  for (const p of progress) {
    if (p.type === "agent_start" && p.agent) started.add(p.agent);
    if (p.type === "agent_done" && p.agent)
      done.set(p.agent, {
        findings: p.findings_count ?? 0,
        elapsed: p.elapsed ?? 0,
      });
    if (p.type === "agent_error" && p.agent)
      errors.set(p.agent, p.error ?? "Unknown error");
  }

  const label = (name: string) =>
    CHECKER_LABELS[name]?.[zh ? "zh" : "en"] ?? name;

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold mb-4">
        {zh ? "檢查進行中..." : "Running checks..."}
      </h2>
      <div className="space-y-2">
        {[...started].map((agent) => {
          const isDone = done.has(agent);
          const isError = errors.has(agent);
          const info = done.get(agent);

          return (
            <div
              key={agent}
              className="bg-[var(--surface)] border border-[var(--border)] rounded-xl p-4 flex items-center justify-between"
            >
              <div className="flex items-center gap-3">
                <span className="text-lg">
                  {isError ? "❌" : isDone ? "✅" : "⏳"}
                </span>
                <span className="font-medium">{label(agent)}</span>
              </div>
              <div className="text-sm text-[#8b90a5]">
                {isError ? (
                  <span className="text-[var(--error)]">
                    {zh ? "失敗" : "Failed"}
                  </span>
                ) : isDone && info ? (
                  <span>
                    {info.findings} {zh ? "個問題" : "findings"} ·{" "}
                    {info.elapsed}s
                  </span>
                ) : (
                  <span className="animate-pulse">
                    {zh ? "分析中..." : "Analyzing..."}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {started.size === 0 && (
        <div className="text-center py-12 text-[#8b90a5] animate-pulse">
          {zh ? "正在連線..." : "Connecting..."}
        </div>
      )}
    </div>
  );
}
