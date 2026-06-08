import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import RunningStep from "../components/RunningStep";
import type { AgentProgress } from "../App";

describe("RunningStep", () => {
  it("shows connecting state when no progress", () => {
    render(<RunningStep progress={[]} lang="en" />);
    expect(screen.getByText(/connecting/i)).toBeInTheDocument();
  });

  it("shows connecting state in Chinese", () => {
    render(<RunningStep progress={[]} lang="zh-TW" />);
    expect(screen.getByText("正在連線至 AI 引擎...")).toBeInTheDocument();
  });

  it("shows agent as running when started", () => {
    const progress: AgentProgress[] = [
      { type: "agent_start", agent: "typo_grammar" },
    ];
    render(<RunningStep progress={progress} lang="en" />);
    expect(screen.getByText("Typo & Grammar")).toBeInTheDocument();
    expect(screen.getByText("Analyzing...")).toBeInTheDocument();
  });

  it("shows agent as done with findings count", () => {
    const progress: AgentProgress[] = [
      { type: "agent_start", agent: "figure_table" },
      { type: "agent_done", agent: "figure_table", findings_count: 3, elapsed: 42.5 },
    ];
    render(<RunningStep progress={progress} lang="en" />);
    expect(screen.getByText("3 findings")).toBeInTheDocument();
    expect(screen.getByText("42.5s")).toBeInTheDocument();
  });

  it("shows progress percentage", () => {
    const progress: AgentProgress[] = [
      { type: "agent_start", agent: "typo_grammar" },
      { type: "agent_start", agent: "figure_table" },
      { type: "agent_done", agent: "typo_grammar", findings_count: 0, elapsed: 10 },
    ];
    render(<RunningStep progress={progress} lang="en" />);
    expect(screen.getByText("50%")).toBeInTheDocument();
  });
});
