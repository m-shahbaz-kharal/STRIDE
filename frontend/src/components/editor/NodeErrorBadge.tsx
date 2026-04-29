import React, { useEffect, useRef, useState } from "react";

import { NodeErrorPayload } from "../../types";

// Phase 3 §7.4 — Inline node-error UI driven by Phase 2's structured
// `error_payload` (NodeError code + message + optional port + details
// + traceback). The badge sits in the node header. Click expands a
// popover with full details. The host (BlueprintNode) is responsible
// for outlining the offending input port in red when `payload.port`
// is set — this component just renders the chip + popover.
//
// Categories per design doc §6.5:
//   • INPUT_ERROR    — bad/missing port input
//   • MISSING_DEP    — depended-on resource not available (puzzle piece)
//   • RUNTIME_ERROR  — exception during run (warning triangle)
//   • CANCELLED      — execution interrupted (X mark)
//   • INTERNAL_ERROR — bug in the node (skull/bug). Show traceback.
//
// Codes that don't match any of the above fall through to a neutral
// "?" icon — we never throw away the badge.

export interface NodeErrorBadgeProps {
  payload: NodeErrorPayload;
  onDismiss?: () => void;
}

interface ErrorCategoryDescriptor {
  label: string;        // Two-letter code (matches design §6.5).
  tone: string;         // CSS class suffix.
  Icon: React.FC<{ size?: number }>;
}

const InputArrowIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    <path d="M5 12h14" />
    <path d="M12 5l7 7-7 7" />
  </svg>
);

const PuzzleIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M19.5 12.5h-1c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5h1c.83 0 1.5-.67 1.5-1.5V6c0-1.1-.9-2-2-2h-2.5C16 4 16 3 16 2.5 16 1.4 14.9 0 13.5 0S11 1.4 11 2.5c0 .5 0 1.5-.5 1.5H8c-1.1 0-2 .9-2 2v3.5C6 9 5 9 4.5 9 3.4 9 2 10.1 2 11.5S3.4 14 4.5 14c.5 0 1.5 0 1.5.5V18c0 1.1.9 2 2 2h3.5c0-.5 1-1.5 2-1.5s2 1 2 1.5H19c1.1 0 2-.9 2-2v-2.5c0-.83-.67-1.5-1.5-1.5z" />
  </svg>
);

const WarningTriangleIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M12 2L1 21h22L12 2zm0 6.5l7.6 13.1H4.4L12 8.5zm-1 4v4h2v-4h-2zm0 5v2h2v-2h-2z" />
  </svg>
);

const XIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" aria-hidden="true">
    <path d="M5 5l14 14M19 5L5 19" />
  </svg>
);

const BugIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M20 8h-2.81a5.985 5.985 0 0 0-1.82-1.96L17 4.41 15.59 3l-2.17 2.17a6.002 6.002 0 0 0-2.83 0L8.41 3 7 4.41l1.62 1.63A5.985 5.985 0 0 0 6.81 8H4v2h2.09c-.05.33-.09.66-.09 1v1H4v2h2v1c0 .34.04.67.09 1H4v2h2.81c1.04 1.79 2.97 3 5.19 3s4.15-1.21 5.19-3H20v-2h-2.09c.05-.33.09-.66.09-1v-1h2v-2h-2v-1c0-.34-.04-.67-.09-1H20V8zm-6 8h-4v-2h4v2zm0-4h-4v-2h4v2z" />
  </svg>
);

const QuestionIcon: React.FC<{ size?: number }> = ({ size = 14 }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    <path d="M11 18h2v-2h-2v2zm1-16C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.41 0-8-3.59-8-8s3.59-8 8-8 8 3.59 8 8-3.59 8-8 8zm0-14c-2.21 0-4 1.79-4 4h2c0-1.1.9-2 2-2s2 .9 2 2c0 2-3 1.75-3 5h2c0-2.25 3-2.5 3-5 0-2.21-1.79-4-4-4z" />
  </svg>
);

const CATEGORY_MAP: Record<string, ErrorCategoryDescriptor> = {
  INPUT_ERROR: { label: "IN", tone: "input", Icon: InputArrowIcon },
  MISSING_DEP: { label: "MD", tone: "missing-dep", Icon: PuzzleIcon },
  RUNTIME_ERROR: { label: "RT", tone: "runtime", Icon: WarningTriangleIcon },
  CANCELLED: { label: "CX", tone: "cancelled", Icon: XIcon },
  INTERNAL_ERROR: { label: "IE", tone: "internal", Icon: BugIcon },
};

const FALLBACK_DESCRIPTOR: ErrorCategoryDescriptor = {
  label: "??",
  tone: "neutral",
  Icon: QuestionIcon,
};

const resolveCategory = (code: string | undefined): ErrorCategoryDescriptor => {
  if (!code) return FALLBACK_DESCRIPTOR;
  // Match by exact code first; fall back to prefix-style ("input.missing"
  // → INPUT_ERROR) so backend evolution doesn't break the badge.
  if (CATEGORY_MAP[code]) return CATEGORY_MAP[code];
  const upper = code.toUpperCase();
  if (upper.includes("INPUT")) return CATEGORY_MAP.INPUT_ERROR;
  if (upper.includes("MISSING") || upper.includes("DEP")) return CATEGORY_MAP.MISSING_DEP;
  if (upper.includes("CANCEL") || upper.includes("INTERRUPT")) return CATEGORY_MAP.CANCELLED;
  if (upper.includes("INTERNAL") || upper.includes("BUG")) return CATEGORY_MAP.INTERNAL_ERROR;
  return CATEGORY_MAP.RUNTIME_ERROR;
};

const truncate = (text: string, max: number): string =>
  text.length > max ? `${text.slice(0, max - 1)}…` : text;

const NodeErrorBadge: React.FC<NodeErrorBadgeProps> = ({ payload, onDismiss }) => {
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);
  const descriptor = resolveCategory(payload.code);
  const Icon = descriptor.Icon;

  // Click-outside closes the popover.
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Node | null;
      if (popoverRef.current && target instanceof Node && !popoverRef.current.contains(target)) {
        setOpen(false);
      }
    };
    // Defer registration so the click that opened the popover doesn't
    // immediately close it.
    const t = setTimeout(() => document.addEventListener("mousedown", handler), 0);
    return () => {
      clearTimeout(t);
      document.removeEventListener("mousedown", handler);
    };
  }, [open]);

  const summary = truncate(payload.message || "Node error", 56);
  const showTraceback = descriptor === CATEGORY_MAP.INTERNAL_ERROR && Boolean(payload.stack_trace);

  return (
    <div
      className={`node-error-badge tone-${descriptor.tone}`}
      data-error-code={payload.code}
      data-testid="node-error-badge"
    >
      <button
        type="button"
        className="node-error-badge-chip nodrag"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((s) => !s);
        }}
        title={payload.message}
      >
        <Icon size={11} />
        <span className="node-error-badge-code">{descriptor.label}</span>
        <span className="node-error-badge-summary">{summary}</span>
      </button>
      {open && (
        <div ref={popoverRef} className="node-error-badge-popover nodrag" onClick={(e) => e.stopPropagation()}>
          <div className="node-error-badge-popover-header">
            <Icon size={14} />
            <strong>{payload.code || "ERROR"}</strong>
            <button
              type="button"
              className="node-error-badge-dismiss"
              title="Dismiss until next run"
              onClick={(e) => {
                e.stopPropagation();
                setOpen(false);
                onDismiss?.();
              }}
            >
              ×
            </button>
          </div>
          <div className="node-error-badge-message">{payload.message}</div>
          {payload.port && (
            <div className="node-error-badge-port">
              Port: <code>{payload.port}</code>
            </div>
          )}
          {payload.details && Object.keys(payload.details).length > 0 && (
            <details className="node-error-badge-details">
              <summary>Details</summary>
              <pre>{JSON.stringify(payload.details, null, 2)}</pre>
            </details>
          )}
          {showTraceback && (
            <details className="node-error-badge-traceback" open>
              <summary>Traceback</summary>
              <pre>{payload.stack_trace}</pre>
            </details>
          )}
        </div>
      )}
    </div>
  );
};

export default NodeErrorBadge;
