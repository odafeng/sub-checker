import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import ReportStep from "../components/ReportStep";
import type { ReportData } from "../App";

const mockReport: ReportData = {
  manuscript_path: "test.docx",
  timestamp: "2026-06-08T12:00:00Z",
  target_journal: "The Lancet",
  model: "claude-opus-4-8",
  total_cost: 5.44,
  summary: { error: 3, warning: 5, info: 2 },
  results: [
    {
      checker: "typo_grammar",
      display_name: "Typo & Grammar",
      elapsed_seconds: 54.0,
      findings: [
        {
          severity: "warning",
          message: "Inconsistent spacing",
          location: "Section: Introduction",
          suggestion: "Fix spacing",
          context: null,
          confidence: 0.9,
          validation_status: "confirmed",
        },
        {
          severity: "info",
          message: "Consider rephrasing",
          location: "Paragraph 5",
          suggestion: null,
          context: null,
          confidence: 0.5,
          validation_status: "downgraded",
        },
      ],
    },
    {
      checker: "figure_table",
      display_name: "Figure & Table",
      elapsed_seconds: 110.0,
      findings: [
        {
          severity: "error",
          message: "Figure 3 missing",
          location: "Section: Results",
          suggestion: "Add Figure3.png",
          context: null,
          confidence: 0.95,
          validation_status: "confirmed",
        },
        {
          severity: "info",
          message: "Filtered finding",
          location: null,
          suggestion: null,
          context: null,
          confidence: 0.0,
          validation_status: "filtered",
        },
      ],
    },
  ],
};

describe("ReportStep", () => {
  it("renders summary cards", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText("3")).toBeInTheDocument(); // errors
    expect(screen.getByText("5")).toBeInTheDocument(); // warnings
    expect(screen.getByText("$5.44")).toBeInTheDocument(); // cost
  });

  it("renders checker sections", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText("Typo & Grammar")).toBeInTheDocument();
    expect(screen.getByText("Figure & Table")).toBeInTheDocument();
  });

  it("renders non-filtered findings and hides filtered ones", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText("Inconsistent spacing")).toBeInTheDocument();
    expect(screen.getByText("Figure 3 missing")).toBeInTheDocument();
    expect(screen.queryByText("Filtered finding")).not.toBeInTheDocument();
  });

  it("renders confidence badges", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText("90%")).toBeInTheDocument(); // confirmed
    expect(screen.getByText("50%")).toBeInTheDocument(); // downgraded
  });

  it("renders model name", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText("claude-opus-4-8")).toBeInTheDocument();
  });

  it("renders download button", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="en" />);
    expect(screen.getByText(/download html/i)).toBeInTheDocument();
  });

  it("renders in Chinese", () => {
    render(<ReportStep report={mockReport} reportHtml="<p>test</p>" lang="zh-TW" />);
    expect(screen.getByText("卡片檢視")).toBeInTheDocument();
    expect(screen.getByText(/下載 HTML/)).toBeInTheDocument();
  });
});
