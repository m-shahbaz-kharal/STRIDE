// Phase 3 §7.4 — NodeErrorBadge snapshot tests across error codes.
// Snapshots cover the rendered chip + open popover for each NodeError
// category from design doc §6.5.

import { describe, expect, it } from "vitest";
import { render, fireEvent } from "@testing-library/react";

import NodeErrorBadge from "./NodeErrorBadge";
import type { NodeErrorPayload } from "../../types";

const make = (overrides: Partial<NodeErrorPayload> = {}): NodeErrorPayload => ({
  code: "RUNTIME_ERROR",
  message: "Something broke",
  ...overrides,
});

const codes = [
  "INPUT_ERROR",
  "MISSING_DEP",
  "RUNTIME_ERROR",
  "CANCELLED",
  "INTERNAL_ERROR",
  "UNKNOWN_CODE", // Falls back through the prefix matcher.
];

describe("NodeErrorBadge", () => {
  it.each(codes)("renders chip for %s", (code) => {
    const { container } = render(<NodeErrorBadge payload={make({ code })} />);
    const chip = container.querySelector(".node-error-badge-chip");
    expect(chip).toBeTruthy();
    // Snapshot the chip closed.
    expect(container.querySelector(".node-error-badge")?.outerHTML).toMatchSnapshot(
      `chip-${code}`
    );
  });

  it("opens popover with details on click", () => {
    const payload = make({
      code: "INPUT_ERROR",
      message: "Port is missing",
      port: "image",
      details: { expected: "image", actual: "string" },
    });
    const { container, getByText } = render(<NodeErrorBadge payload={payload} />);
    const chip = container.querySelector(".node-error-badge-chip") as HTMLElement;
    fireEvent.click(chip);
    expect(getByText("INPUT_ERROR")).toBeTruthy();
    // The message appears both in the chip summary and the popover —
    // assert the popover instance directly.
    const popoverMessage = container.querySelector(".node-error-badge-message");
    expect(popoverMessage?.textContent).toBe("Port is missing");
    // Port badge is shown.
    expect(container.querySelector(".node-error-badge-port")).toBeTruthy();
  });

  it("shows traceback by default for INTERNAL_ERROR", () => {
    const payload = make({
      code: "INTERNAL_ERROR",
      message: "Crash",
      stack_trace: "Traceback (most recent call last):\n  File ...",
    });
    const { container } = render(<NodeErrorBadge payload={payload} />);
    const chip = container.querySelector(".node-error-badge-chip") as HTMLElement;
    fireEvent.click(chip);
    const trace = container.querySelector(".node-error-badge-traceback");
    expect(trace).toBeTruthy();
    expect(trace?.getAttribute("open")).not.toBeNull();
  });

  it("calls onDismiss when dismiss button is clicked", () => {
    let dismissed = false;
    const onDismiss = () => {
      dismissed = true;
    };
    const { container } = render(
      <NodeErrorBadge payload={make({ code: "RUNTIME_ERROR" })} onDismiss={onDismiss} />
    );
    fireEvent.click(container.querySelector(".node-error-badge-chip") as HTMLElement);
    fireEvent.click(container.querySelector(".node-error-badge-dismiss") as HTMLElement);
    expect(dismissed).toBe(true);
  });

  it("falls back to neutral styling for unknown short codes", () => {
    const { container } = render(<NodeErrorBadge payload={make({ code: "" })} />);
    const badge = container.querySelector(".node-error-badge");
    expect(badge?.className).toContain("tone-neutral");
  });
});
