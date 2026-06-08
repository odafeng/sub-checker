import { render, screen } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import UploadStep from "../components/UploadStep";

describe("UploadStep", () => {
  it("renders upload area in English", () => {
    render(<UploadStep onUploaded={vi.fn()} lang="en" />);
    expect(screen.getByText(/drop your manuscript/i)).toBeInTheDocument();
    expect(screen.getByText(/choose .docx file/i)).toBeInTheDocument();
  });

  it("renders upload area in Chinese", () => {
    render(<UploadStep onUploaded={vi.fn()} lang="zh-TW" />);
    expect(screen.getByText("拖拽文稿到此處")).toBeInTheDocument();
    expect(screen.getByText("選擇 .docx 檔案")).toBeInTheDocument();
  });

  it("has a file input that accepts .docx", () => {
    render(<UploadStep onUploaded={vi.fn()} lang="en" />);
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    expect(input).toBeTruthy();
    expect(input.accept).toBe(".docx");
  });
});
