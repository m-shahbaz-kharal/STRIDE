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
  const baseStroke = (style as React.CSSProperties)?.stroke || "#4a9eff";
  const strokeColor = selected
    ? "var(--selection-yellow)"
    : isPreview
      ? "var(--selection-yellow)"
      : isHovered
        ? "var(--selection-yellow-light)"
        : baseStroke;
  const strokeWidth = selected ? 3 : isPreview ? 2.5 : isHovered ? 2.5 : ((style as React.CSSProperties)?.strokeWidth as number) || 2;
  const dashOverride = (style as React.CSSProperties)?.strokeDasharray as string | undefined;
  const dashPattern = isControl ? (dashOverride || "6 4") : dashOverride;

  return (
    <g
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
      className={`custom-edge ${selected ? "selected" : ""} ${isHovered ? "hovered" : ""} ${isPreview ? "preview" : ""}`}
    >
      <path
        d={edgePath}
        fill="none"
        stroke="transparent"
        strokeWidth={20}
        style={{ cursor: "pointer" }}
      />
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
      {isControl && (
        <g transform={`translate(${labelX - 10}, ${labelY - 10})`}>
          <rect
            x={0}
            y={0}
            rx={4}
            width={38}
            height={18}
            fill="rgba(249,115,22,0.15)"
            stroke="rgba(249,115,22,0.9)"
            strokeWidth={1}
          />
          <text
            x={6}
            y={12}
            fill="rgba(249,115,22,0.95)"
            fontSize="10"
            fontFamily="monospace"
          >
            control
          </text>
        </g>
      )}
      {(isHovered || selected) && !isPreview && (
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

  // Check style changes
  const prevStyle = prev.style as React.CSSProperties | undefined;
  const nextStyle = next.style as React.CSSProperties | undefined;
  if (prevStyle?.stroke !== nextStyle?.stroke) return false;
  if (prevStyle?.strokeWidth !== nextStyle?.strokeWidth) return false;
  if (prevStyle?.strokeDasharray !== nextStyle?.strokeDasharray) return false;

  return true;
});
