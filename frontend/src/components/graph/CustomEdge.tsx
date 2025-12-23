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
  const baseStroke = (style as React.CSSProperties)?.stroke || "#4a9eff";
  const strokeColor = selected
    ? "var(--selection-yellow)"
    : isPreview
      ? "var(--selection-yellow)"
      : isHovered
        ? "var(--selection-yellow-light)"
        : baseStroke;
  const strokeWidth = selected ? 3 : isPreview ? 2.5 : isHovered ? 2.5 : ((style as React.CSSProperties)?.strokeWidth as number) || 2;

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
        }}
        markerEnd={markerEnd}
      />
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

export default CustomEdge;
