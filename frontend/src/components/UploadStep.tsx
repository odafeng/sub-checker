import { useState, useCallback, useRef } from "react";
import type { ManuscriptInfo } from "../App";

interface Props {
  onUploaded: (info: ManuscriptInfo) => void;
  lang: string;
}

function DocIcon() {
  return (
    <svg
      width="40"
      height="40"
      viewBox="0 0 24 24"
      fill="none"
      className="mx-auto"
      aria-hidden="true"
    >
      <path
        d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"
        stroke="var(--accent)"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
      <path d="M14 2v6h6" stroke="var(--accent)" strokeWidth="1.5" strokeLinejoin="round" />
      <path
        d="M9 13h6M9 17h6"
        stroke="var(--text-dim)"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  );
}

function SmallSpinner() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" className="animate-spin" aria-hidden="true">
      <circle
        cx="12"
        cy="12"
        r="10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeOpacity="0.25"
      />
      <path
        d="M12 2a10 10 0 0 1 10 10"
        fill="none"
        stroke="currentColor"
        strokeWidth="3"
        strokeLinecap="round"
      />
    </svg>
  );
}

export default function UploadStep({ onUploaded, lang }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const zh = lang === "zh-TW";

  const upload = useCallback(
    async (file: File) => {
      if (!file.name.endsWith(".docx")) {
        setError(zh ? "請上傳 .docx 檔案" : "Please upload a .docx file");
        return;
      }
      setUploading(true);
      setError("");
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch("/api/upload", { method: "POST", body: form });
        const data = await res.json().catch(() => null);
        if (!res.ok || !data) {
          setError(
            data?.detail ??
              data?.error ??
              (zh ? `上傳失敗 (${res.status})` : `Upload failed (${res.status})`)
          );
        } else {
          onUploaded(data);
        }
      } catch {
        setError(zh ? "上傳失敗" : "Upload failed");
      } finally {
        setUploading(false);
      }
    },
    [onUploaded, zh]
  );

  return (
    <div
      className={`border-2 border-dashed rounded-2xl p-16 text-center transition-colors cursor-pointer ${
        dragging
          ? "border-[var(--accent)] bg-[var(--accent)]/5"
          : "border-[var(--border)] hover:border-[var(--accent)]/50"
      } ${uploading ? "opacity-60" : ""}`}
      onClick={(e) => {
        // Programmatic input.click() bubbles back here — ignore it
        if (uploading || e.target === inputRef.current) return;
        inputRef.current?.click();
      }}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={(e) => {
        if (e.currentTarget.contains(e.relatedTarget as Node)) return;
        setDragging(false);
      }}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        if (uploading) return;
        const file = e.dataTransfer.files[0];
        if (file) upload(file);
      }}
    >
      <div className="mb-4">
        <DocIcon />
      </div>
      <p className="text-lg font-medium mb-2">
        {zh ? "拖拽文稿到此處" : "Drop your manuscript here"}
      </p>
      <p className="text-sm text-[var(--text-dim)] mb-6">
        {zh ? "或點擊下方按鈕選擇檔案" : "or click below to select a file"}
      </p>
      <button
        type="button"
        disabled={uploading}
        onClick={(e) => {
          e.stopPropagation();
          inputRef.current?.click();
        }}
        className="inline-flex items-center gap-2 cursor-pointer bg-[var(--accent)] hover:bg-[var(--accent-hover)] disabled:opacity-60 disabled:cursor-default text-white font-medium px-6 py-2.5 rounded-xl transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--accent)]"
      >
        {uploading && <SmallSpinner />}
        {uploading
          ? zh
            ? "上傳中..."
            : "Uploading..."
          : zh
          ? "選擇 .docx 檔案"
          : "Choose .docx file"}
      </button>
      <input
        ref={inputRef}
        type="file"
        accept=".docx"
        disabled={uploading}
        className="sr-only"
        onChange={(e) => {
          const file = e.target.files?.[0];
          // Reset so re-selecting the same file after a failure fires onChange again
          e.target.value = "";
          if (file) upload(file);
        }}
      />
      <p className="mt-4 text-xs text-[var(--text-dim)]">
        {zh
          ? ".docx · 最大 20 MB · 檔案僅供本次檢查暫時儲存"
          : ".docx · max 20 MB · files are stored temporarily for this check only"}
      </p>
      {error && <p className="mt-4 text-[var(--error)]">{error}</p>}
    </div>
  );
}
