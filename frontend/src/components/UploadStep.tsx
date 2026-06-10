import { useState, useCallback } from "react";
import type { ManuscriptInfo } from "../App";

interface Props {
  onUploaded: (info: ManuscriptInfo) => void;
  lang: string;
}

export default function UploadStep({ onUploaded, lang }: Props) {
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
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
      className={`border-2 border-dashed rounded-2xl p-16 text-center transition-colors ${
        dragging
          ? "border-[var(--accent)] bg-[var(--accent)]/5"
          : "border-[var(--border)] hover:border-[var(--accent)]/50"
      }`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) upload(file);
      }}
    >
      <div className="text-4xl mb-4">📄</div>
      <p className="text-lg font-medium mb-2">
        {zh ? "拖拽文稿到此處" : "Drop your manuscript here"}
      </p>
      <p className="text-sm text-[#8b90a5] mb-6">
        {zh ? "或點擊下方按鈕選擇檔案" : "or click below to select a file"}
      </p>
      <label className="inline-block cursor-pointer bg-[var(--accent)] hover:bg-[var(--accent)]/80 text-white font-medium px-6 py-2.5 rounded-xl transition-colors">
        {uploading
          ? zh
            ? "上傳中..."
            : "Uploading..."
          : zh
          ? "選擇 .docx 檔案"
          : "Choose .docx file"}
        <input
          type="file"
          accept=".docx"
          className="hidden"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) upload(file);
          }}
        />
      </label>
      {error && <p className="mt-4 text-[var(--error)]">{error}</p>}
    </div>
  );
}
