import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import App from "../App";

describe("App", () => {
  it("renders the header", () => {
    render(<App />);
    expect(screen.getByText("Sub-Checker")).toBeInTheDocument();
  });

  it("renders the language switcher with both options", () => {
    render(<App />);
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByText("English")).toBeInTheDocument();
    expect(screen.getByText("繁體中文")).toBeInTheDocument();
  });

  it("starts on the upload step", () => {
    render(<App />);
    expect(screen.getByText(/drop your manuscript/i)).toBeInTheDocument();
  });
});
