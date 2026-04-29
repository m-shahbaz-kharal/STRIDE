import React, { useState } from "react";
import { EdgeProps, getBezierPath, useReactFlow } from "reactflow";

const CustomEdge = ({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  style = {},
  markerEnd,
  selected,
  data,
}: EdgeProps) => {
  const [isHovered, setIsHovered] = useState(false);
  const [showInvalidPopover, setShowInvalidPopover] = useState(false);
  const { setEdges } = useReactFlow();

  const [edgePath, labelX, labelY] = getBezierPath({
    sourceX,
    sourceY,
    sourcePosition,
    targetX,
    targetY,
    targetPosition,
  });

  const handleDeleteEdge = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEdges((edges) => edges.filter((edge) => edge.id !== id));
  };

  const isPreview = data?.isPreview ?? false;
  const isControl = data?.kind === "control";
  // Phase 3 §7.3 — edge revalidation: when a param change makes this
  // edge incompatible, App.tsx sets data.invalid; we render a red `!`
  // badge mid-edge. Click reveals the reason in a popover.
  const isInvalid: boolean = data?.invalid === true;
  const invalidReason: string | undefined = data?.invalidReason;
  // Phase 3 §7.6 — extract type-info hover tooltip from data populated
  // by handleConnect (sourceLabel/targetLabel populated below in App).
  const typeTooltip: string | undefined = data?.typeTooltip;
  // Phase 3 §7.6 — visual style hint: "compatible" | "convertible" |
  // "any-bridge" — drives solid / dashed / double-dashed rendering.
  const dashStyle: string | undefined = data?.dashStyle;

  const baseStroke = (style as React.CSSProperties)?.stroke || "#4a9eff";
  const strokeColor = isInvalid
    ? "var(--accent-red, #ef4444)"
    : selected
      ? "var(--selection-yellow)"
      : isPreview
        ? "var(--selection-yellow)"
        : isHovered
          ? "var(--selection-yellow-light)"
          : baseStroke;
  const strokeWidth = selected ? 3 : isPreview ? 2.5 : isHovered ? 2.5 : ((style as React.CSSProperties)?.strokeWidth as number) || 2;
  const dashOverride = (style as React.CSSProperties)?.strokeDasharray as string | undefined;
  const semanticDash =
    dashStyle === "convertible" ? "6 5" :
    dashStyle === "any-bridge" ? "2 4 8 4" :
    undefined;
  const dashPattern = isControl
    ? (dashOverride || "6 4")
    : (dashOverride || semanticDash);

  return (
    <g
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`custom-edge ${selected ? "selected" : ""} ${isHovered ? "hovered" : ""} ${isPreview ? "preview" : ""} ${isInvalid ? "invalid" : ""}`}
    >
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        style={{ cursor: "pointer" }}
      >
        {(typeTooltip || invalidReason) && (
          <title>{invalidReason ? `⚠ ${invalidReason}` : typeTooltip}</title>
        )}
      </path>
      <path
        id={id}
        className="react-flow__edge-path"
        d={edgePath}
        style={{
          ...style,
          stroke: strokeColor,
          strokeWidth,
          transition: "stroke 0.1s ease, stroke-width 0.1s ease",
          strokeDasharray: dashPattern,
        }}
        markerEnd={markerEnd}
      />
      {/* Phase 3 §7.3 — invalid-edge `!` badge. */}
      {isInvalid && !isPreview && (
        <g
          transform={`translate(${labelX - 9}, ${labelY - 9})`}
          onClick={(e) => {
            e.stopPropagation();
            setShowInvalidPopover((s) => !s);
          }}
          style={{ cursor: "pointer" }}
        >
          <circle r="9" cx="9" cy="9" fill="var(--accent-red, #ef4444)" stroke="white" strokeWidth="1.5" />
          <text
            x="9"
            y="13"
            textAnchor="middle"
            fontSize="12"
            fontWeight="700"
            fill="white"
            style={{ userSelect: "none" }}
          >
            !
          </text>
          <title>{invalidReason || "Edge type mismatch"}</title>
        </g>
      )}
      {isInvalid && showInvalidPopover && (
        <foreignObject x={labelX + 12} y={labelY - 18} width={260} height={56} style={{ overflow: "visible" }}>
          <div
            style={{
              background: "var(--bg-elevated, #1e293b)",
              color: "var(--text-primary, white)",
              padding: "8px 10px",
              borderRadius: 6,
              fontSize: 11,
              border: "1px solid var(--accent-red, #ef4444)",
              boxShadow: "0 4px 14px rgba(0,0,0,0.4)",
              lineHeight: 1.4,
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <strong style={{ color: "var(--accent-red, #ef4444)" }}>Type mismatch</strong>
            <div>{invalidReason}</div>
          </div>
        </foreignObject>
      )}
      {(isHovered || selected) && !isPreview && !isInvalid && (
        <g
          transform={`translate(${labelX - 8}, ${labelY - 8})`}
          onClick={handleDeleteEdge}
          style={{ cursor: "pointer" }}
        >
          <circle
            r="8"
            cx="8"
            cy="8"
            fill={selected ? "var(--selection-yellow)" : "var(--selection-yellow-light)"}
          />
          <path
            d="M5 5L11 11M11 5L5 11"
            stroke="var(--bg-deep)"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </g>
      )}
    </g>
  );
};

// PERF: Memoize edge to prevent re-renders when other edges change
export default React.memo(CustomEdge, (prev, next) => {
  // Only re-render if position, selection, or styling actually changed
  if (prev.id !== next.id) return false;
  if (prev.sourceX !== next.sourceX || prev.sourceY !== next.sourceY) return false;
  if (prev.targetX !== next.targetX || prev.targetY !== next.targetY) return false;
  if (prev.sourcePosition !== next.sourcePosition) return false;
  if (prev.targetPosition !== next.targetPosition) return false;
  if (prev.selected !== next.selected) return false;
  if (prev.data?.isPreview !== next.data?.isPreview) return false;
  if (prev.data?.kind !== next.data?.kind) return false;
  if (prev.data?.invalid !== next.data?.invalid) return false;
  if (prev.data?.invalidReason !== next.data?.invalidReason) return false;
  if (prev.data?.dashStyle !== next.data?.dashStyle) return false;
  if (prev.data?.typeTooltip !== next.data?.typeTooltip) return false;

  // Check style changes
  const prevStyle = prev.style as React.CSSProperties | undefined;
  const nextStyle = next.style as React.CSSProperties | undefined;
  if (prevStyle?.stroke !== nextStyle?.stroke) return false;
  if (prevStyle?.strokeWidth !== nextStyle?.strokeWidth) return false;
  if (prevStyle?.strokeDasharray !== nextStyle?.strokeDasharray) return false;

  return true;
});
