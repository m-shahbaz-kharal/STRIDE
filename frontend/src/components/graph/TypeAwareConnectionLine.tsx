import React from "react";
import { ConnectionLineComponentProps, getBezierPath } from "reactflow";

const TypeAwareConnectionLine = ({
  fromX,
  fromY,
  toX,
  toY,
  fromPosition,
  toPosition,
  connectionLineStyle,
  connectionStatus,
}: ConnectionLineComponentProps) => {
  const [path] = getBezierPath({
    sourceX: fromX,
    sourceY: fromY,
    sourcePosition: fromPosition,
    targetX: toX,
    targetY: toY,
    targetPosition: toPosition,
  });

  const isInvalid = connectionStatus === "invalid";
  const stroke = isInvalid
    ? "var(--status-error)"
    : ((connectionLineStyle as React.CSSProperties | undefined)?.stroke as string) || "#4a9eff";
  const glow = isInvalid ? "rgba(248, 81, 73, 0.9)" : "rgba(74, 158, 255, 0.35)";
  const strokeWidth = isInvalid ? 3.2 : 2.5;

  return (
    <g className={`connection-line ${isInvalid ? "invalid" : "valid"}`}>
      <path d={path} fill="none" stroke="transparent" strokeWidth={18} />
      <path
        d={path}
        fill="none"
        stroke={stroke}
        strokeWidth={strokeWidth}
        style={{
          ...connectionLineStyle,
          filter: `drop-shadow(0 0 8px ${glow})`,
          transition: "stroke 0.08s ease, stroke-width 0.08s ease",
        }}
        strokeDasharray={isInvalid ? "10 4" : undefined}
      />
    </g>
  );
};

export default TypeAwareConnectionLine;
