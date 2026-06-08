import { useState, useEffect } from "react";
import type { ManuscriptInfo } from "../App";

interface Checker {
  name: string;
  label_en: string;
  label_zh: string;
}

interface Props {
  manuscript: ManuscriptInfo;
  onStart: (journal: string, checkers: string[]) => void;
  lang: string;
}

export default function ConfigStep({ manuscript, onStart, lang }: Props) {
  const [journal, setJournal] = useState("");
  const [checkers, setCheckers] = useState<Checker[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const zh = lang === "zh-TW";

  useEffect(() => {
    fetch("/api/checkers")
      .then((r) => r.json())
      .then((data: Checker[]) => {
        setCheckers(data);
        setSelected(new Set(data.map((c) => c.name)));
      });
  }, []);

  const toggle = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  return (
    <div className="space-y-6">
      {/* Manuscript info card */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-6">
        <h2 className="font-semibold text-lg mb-3">
          {zh ? "文稿資訊" : "Manuscript Info"}
        </h2>
        <div className="grid grid-cols-2 gap-3 text-sm">
          <div>
            <span className="text-[#8b90a5]">
              {zh ? "檔案名稱" : "Filename"}:
            </span>{" "}
            {manuscript.filename}
          </div>
          <div>
            <span className="text-[#8b90a5]">
              {zh ? "字數" : "Words"}:
            </span>{" "}
            {manuscript.word_count.toLocaleString()}
          </div>
          <div>
            <span className="text-[#8b90a5]">
              {zh ? "段落數" : "Paragraphs"}:
            </span>{" "}
            {manuscript.paragraph_count}
          </div>
          <div>
            <span className="text-[#8b90a5]">
              {zh ? "參考文獻" : "References"}:
            </span>{" "}
            {manuscript.has_references ? "✓" : "✗"}
          </div>
        </div>
      </div>

      {/* Journal */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-6">
        <h2 className="font-semibold text-lg mb-3">
          {zh ? "目標期刊" : "Target Journal"}
        </h2>
        <input
          type="text"
          placeholder={
            zh
              ? '例如: "The Lancet", "Nature Medicine"'
              : 'e.g. "The Lancet", "Nature Medicine"'
          }
          value={journal}
          onChange={(e) => setJournal(e.target.value)}
          className="w-full bg-[var(--bg)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm focus:border-[var(--accent)] outline-none"
        />
      </div>

      {/* Checker selection */}
      <div className="bg-[var(--surface)] border border-[var(--border)] rounded-2xl p-6">
        <div className="flex items-center justify-between mb-3">
          <h2 className="font-semibold text-lg">
            {zh ? "檢查項目" : "Checkers"}
          </h2>
          <button
            onClick={() =>
              setSelected((prev) =>
                prev.size === checkers.length
                  ? new Set()
                  : new Set(checkers.map((c) => c.name))
              )
            }
            className="text-xs text-[var(--accent)]"
          >
            {selected.size === checkers.length
              ? zh
                ? "全部取消"
                : "Deselect All"
              : zh
              ? "全部選取"
              : "Select All"}
          </button>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {checkers.map((c) => (
            <label
              key={c.name}
              className={`flex items-center gap-3 p-3 rounded-xl cursor-pointer transition-colors ${
                selected.has(c.name)
                  ? "bg-[var(--accent)]/10 border border-[var(--accent)]/30"
                  : "bg-[var(--bg)] border border-[var(--border)]"
              }`}
            >
              <input
                type="checkbox"
                checked={selected.has(c.name)}
                onChange={() => toggle(c.name)}
                className="accent-[var(--accent)]"
              />
              <span className="text-sm">
                {zh ? c.label_zh : c.label_en}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Start button */}
      <button
        onClick={() => onStart(journal, [...selected])}
        disabled={selected.size === 0}
        className="w-full bg-[var(--accent)] hover:bg-[var(--accent)]/80 disabled:opacity-40 text-white font-semibold py-3 rounded-xl text-lg transition-colors"
      >
        {zh
          ? `開始檢查 (${selected.size} 個項目)`
          : `Start Check (${selected.size} checkers)`}
      </button>
    </div>
  );
}
