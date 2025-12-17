import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  EdgeProps,
  getBezierPath,
  Handle,
  MiniMap,
  Node,
  NodeProps,
  OnSelectionChangeParams,
  Position,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
  useReactFlow,
  SelectionMode,
  ReactFlowInstance,
} from "reactflow";
import "reactflow/dist/style.css";

import LogPanel from "./components/LogPanel";
import NodeInspector from "./components/NodeInspector";
import NodePalette from "./components/NodePalette";
import OutputsView from "./components/OutputsView";
import SmartConnectModal from "./components/SmartConnectModal";
import { useGraphExecution } from "./hooks/useGraphExecution";
import { useUndoRedo } from "./hooks/useUndoRedo";
import {
  BlueprintNodeData,
  NodeExecutionStatus,
  NodeTypeDefinition,
} from "./types";

// Right panel tab type
type RightPanelTab = "inspector" | "execution";

// Helper: Check if a line segment intersects a rectangle
const lineIntersectsRect = (
  x1: number, y1: number, x2: number, y2: number,
  rx: number, ry: number, rw: number, rh: number
): boolean => {
  // Check if either endpoint is inside the rectangle
  const pointInRect = (px: number, py: number) =>
    px >= rx && px <= rx + rw && py >= ry && py <= ry + rh;

  if (pointInRect(x1, y1) || pointInRect(x2, y2)) return true;

  // Check line intersection with each edge of the rectangle
  const lineIntersectsLine = (
    ax1: number, ay1: number, ax2: number, ay2: number,
    bx1: number, by1: number, bx2: number, by2: number
  ): boolean => {
    const denom = (by2 - by1) * (ax2 - ax1) - (bx2 - bx1) * (ay2 - ay1);
    if (Math.abs(denom) < 0.0001) return false;

    const ua = ((bx2 - bx1) * (ay1 - by1) - (by2 - by1) * (ax1 - bx1)) / denom;
    const ub = ((ax2 - ax1) * (ay1 - by1) - (ay2 - ay1) * (ax1 - bx1)) / denom;

    return ua >= 0 && ua <= 1 && ub >= 0 && ub <= 1;
  };

  // Check all four edges of rectangle
  return (
    lineIntersectsLine(x1, y1, x2, y2, rx, ry, rx + rw, ry) || // top
    lineIntersectsLine(x1, y1, x2, y2, rx, ry + rh, rx + rw, ry + rh) || // bottom
    lineIntersectsLine(x1, y1, x2, y2, rx, ry, rx, ry + rh) || // left
    lineIntersectsLine(x1, y1, x2, y2, rx + rw, ry, rx + rw, ry + rh) // right
  );
};

// Helper: Sample points along a bezier curve and check if any segment intersects the rect
const bezierIntersectsRect = (
  sourceX: number, sourceY: number,
  targetX: number, targetY: number,
  rx: number, ry: number, rw: number, rh: number
): boolean => {
  // Calculate control points for bezier (similar to ReactFlow's default)
  const centerX = (sourceX + targetX) / 2;
  const cp1x = centerX;
  const cp1y = sourceY;
  const cp2x = centerX;
  const cp2y = targetY;

  // Sample the bezier curve and check line segments
  const samples = 20;
  let prevX = sourceX;
  let prevY = sourceY;

  for (let i = 1; i <= samples; i++) {
    const t = i / samples;
    const t2 = t * t;
    const t3 = t2 * t;
    const mt = 1 - t;
    const mt2 = mt * mt;
    const mt3 = mt2 * mt;

    // Cubic bezier formula
    const x = mt3 * sourceX + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * targetX;
    const y = mt3 * sourceY + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * targetY;

    if (lineIntersectsRect(prevX, prevY, x, y, rx, ry, rw, rh)) {
      return true;
    }

    prevX = x;
    prevY = y;
  }

  return false;
};

// Value Preview Popup Component
interface ValuePopupProps {
  value: unknown;
  title: string;
  onClose: () => void;
}

const ValuePopup = ({ value, title, onClose }: ValuePopupProps) => {
  const [size, setSize] = useState({ width: 400, height: 300 });
  const [position, setPosition] = useState({ x: window.innerWidth / 2 - 200, y: window.innerHeight / 2 - 150 });
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0 });

  const formatValue = (val: unknown): string => {
    if (val === null || val === undefined) return "null";
    if (typeof val === "string") return val;
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    try {
      return JSON.stringify(val, null, 2);
    } catch {
      return String(val);
    }
  };

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        setPosition({
          x: dragStartRef.current.posX + dx,
          y: dragStartRef.current.posY + dy,
        });
      }
      if (isResizing) {
        const dx = e.clientX - resizeStartRef.current.x;
        const dy = e.clientY - resizeStartRef.current.y;
        setSize({
          width: Math.max(200, resizeStartRef.current.width + dx),
          height: Math.max(150, resizeStartRef.current.height + dy),
        });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    if (isDragging || isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, isResizing]);

  const handleDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragStartRef.current = { x: e.clientX, y: e.clientY, posX: position.x, posY: position.y };
    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeStartRef.current = { x: e.clientX, y: e.clientY, width: size.width, height: size.height };
    setIsResizing(true);
  };

  return (
    <div className="value-popup-overlay" onClick={onClose}>
      <div
        className="value-popup"
        style={{ left: position.x, top: position.y, width: size.width, height: size.height }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="value-popup-header" onMouseDown={handleDragStart}>
          <span className="value-popup-title">{title}</span>
          <button className="value-popup-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
            </svg>
          </button>
        </div>
        <div className="value-popup-content">
          <pre>{formatValue(value)}</pre>
        </div>
        <div className="value-popup-resize" onMouseDown={handleResizeStart}>
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
      </div>
    </div>
  );
};

// Node Logs Popup Component
interface LogsPopupProps {
  nodeId: string;
  nodeName: string;
  logs: string[];
  onClose: () => void;
}

const LogsPopup = ({ nodeId, nodeName, logs, onClose }: LogsPopupProps) => {
  const [size, setSize] = useState({ width: 450, height: 300 });
  const [position, setPosition] = useState({ x: window.innerWidth / 2 - 225, y: window.innerHeight / 2 - 150 });
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        setPosition({
          x: dragStartRef.current.posX + dx,
          y: dragStartRef.current.posY + dy,
        });
      }
      if (isResizing) {
        const dx = e.clientX - resizeStartRef.current.x;
        const dy = e.clientY - resizeStartRef.current.y;
        setSize({
          width: Math.max(250, resizeStartRef.current.width + dx),
          height: Math.max(150, resizeStartRef.current.height + dy),
        });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    if (isDragging || isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, isResizing]);

  const handleDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragStartRef.current = { x: e.clientX, y: e.clientY, posX: position.x, posY: position.y };
    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeStartRef.current = { x: e.clientX, y: e.clientY, width: size.width, height: size.height };
    setIsResizing(true);
  };

  return (
    <div className="value-popup-overlay" onClick={onClose}>
      <div
        className="value-popup logs-popup"
        style={{ left: position.x, top: position.y, width: size.width, height: size.height }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="value-popup-header" onMouseDown={handleDragStart}>
          <span className="value-popup-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 6 }}>
              <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" />
            </svg>
            Logs: {nodeName}
          </span>
          <button className="value-popup-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
            </svg>
          </button>
        </div>
        <div className="value-popup-content logs-content">
          {logs.length === 0 ? (
            <div className="logs-empty">No logs available for this node.</div>
          ) : (
            logs.map((log, i) => (
              <div key={i} className="log-line">
                <span className="log-line-number">{i + 1}</span>
                <span className="log-line-content">{log}</span>
              </div>
            ))
          )}
        </div>
        <div className="value-popup-resize" onMouseDown={handleResizeStart}>
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
      </div>
    </div>
  );
};

const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
};

// Global state for popups (to avoid prop drilling through ReactFlow)
let globalShowValuePopup: ((value: unknown, title: string) => void) | null = null;
let globalShowLogsPopup: ((nodeId: string, nodeName: string, logs: string[]) => void) | null = null;

const OutputValue = ({ port, value }: { port: string; value: unknown }) => {
  const formatted = formatValue(value);
  const isLong = formatted.length > 12;
  const displayValue = isLong ? formatted.slice(0, 10) + "…" : formatted;

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (globalShowValuePopup) {
      globalShowValuePopup(value, `Output: ${port}`);
    }
  };

  return (
    <span
      className={`node-output-value ${isLong ? "expandable" : ""}`}
      onClick={handleClick}
      title={isLong ? "Click to view full value" : formatted}
    >
      = {displayValue}
    </span>
  );
};

type Corner = "top-left" | "top-right" | "bottom-left" | "bottom-right" | null;

interface ResizeZoneProps {
  corner: Corner;
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onMouseDown: (e: React.MouseEvent) => void;
}

const ResizeZone = ({ corner, isHovered, onMouseEnter, onMouseLeave, onMouseDown }: ResizeZoneProps) => {
  if (!corner) return null;

  const isTop = corner.includes("top");
  const isLeft = corner.includes("left");
  const cursor = (corner === "top-left" || corner === "bottom-right") ? "nwse-resize" : "nesw-resize";
  const rotation = corner === "top-left" ? 0 :
    corner === "top-right" ? 90 :
      corner === "bottom-right" ? 180 : 270;

  // Position zone mostly outside the node - only activates at corner or slightly outside
  const zoneSize = 16;
  const zoneOffset = corner === "bottom-right" ? `-${zoneSize - 4}px` : "-2px";

  return (
    <div
      className={`resize-zone nodrag ${corner}`}
      style={{
        position: "absolute",
        [isTop ? "top" : "bottom"]: zoneOffset,
        [isLeft ? "left" : "right"]: zoneOffset,
        width: `${zoneSize}px`,
        height: `${zoneSize}px`,
        cursor,
        zIndex: 20,
      }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
      onMouseDown={onMouseDown}
    >
      {isHovered && (
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          style={{
            position: "absolute",
            // Position icon outside the node corner
            top: corner === "bottom-right" ? "2px" : "3px",
            left: corner === "bottom-right" ? "2px" : "3px",
            transform: `rotate(${rotation}deg)`,
            transformOrigin: "6px 6px",
            pointerEvents: "none",
          }}
        >
          <path
            d="M 1 10 L 1 6 Q 1 1 6 1 L 10 1"
            fill="none"
            stroke="var(--accent-blue)"
            strokeWidth="2"
            strokeLinecap="round"
          />
        </svg>
      )}
    </div>
  );
};

// Get status-based styling for nodes
const getExecutionStatusClass = (status?: NodeExecutionStatus): string => {
  switch (status) {
    case "running":
      return "node-running";
    case "queued":
      return "node-queued";
    case "completed":
      return "node-executed";
    case "error":
      return "node-error";
    default:
      return "";
  }
};

// Custom Edge with delete button, hover, selection, and preview states
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

  // Check if edge is in preview mode (during selection drag)
  const isPreview = data?.isPreview ?? false;

  // Determine stroke color and width based on state
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
      {/* Invisible wider path for easier interaction */}
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

const BlueprintNode = ({ id, data }: NodeProps<BlueprintNodeData>) => {
  const [hoveredCorner, setHoveredCorner] = useState<Corner>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [nodeSize, setNodeSize] = useState({ width: data.width || 0, height: data.height || 0 });
  const nodeRef = useRef<HTMLDivElement>(null);
  const startPosRef = useRef({ x: 0, y: 0, width: 0, height: 0 });
  const resizeCornerRef = useRef<Corner>(null);
  const zoomRef = useRef(1);
  const { getZoom } = useReactFlow();

  const executionStatusClass = getExecutionStatusClass(data.executionStatus);
  const statusClass = executionStatusClass || (data.last_outputs ? "node-executed" : "");
  const highlightClass = data.isHighlighted ? "node-highlighted" : "";

  const handleResizeStart = useCallback((corner: Corner, e: React.MouseEvent) => {
    if (!corner || !nodeRef.current) return;

    e.stopPropagation();
    e.preventDefault();
    const width = nodeRef.current.offsetWidth;
    const height = nodeRef.current.offsetHeight;
    startPosRef.current = { x: e.clientX, y: e.clientY, width, height };
    resizeCornerRef.current = corner;
    zoomRef.current = getZoom(); // Capture zoom level at resize start
    setNodeSize({ width, height });
    setIsResizing(true);
  }, [getZoom]);

  const maxPorts = Math.max(data.input_ports.length, data.output_ports.length);
  // Calculate min dimensions based on content
  // Header ~36px, each port row ~24px, padding ~16px
  const MIN_WIDTH = 200;
  const MIN_HEIGHT = 64 + maxPorts * 26;

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const corner = resizeCornerRef.current;
      if (!corner) return;

      // Adjust delta by zoom level so resize matches mouse position exactly
      const zoom = zoomRef.current;
      const dx = (e.clientX - startPosRef.current.x) / zoom;
      const dy = (e.clientY - startPosRef.current.y) / zoom;

      let newWidth = startPosRef.current.width;
      let newHeight = startPosRef.current.height;

      if (corner === "bottom-right") {
        newWidth += dx;
        newHeight += dy;
      } else if (corner === "bottom-left") {
        newWidth -= dx;
        newHeight += dy;
      } else if (corner === "top-right") {
        newWidth += dx;
        newHeight -= dy;
      } else if (corner === "top-left") {
        newWidth -= dx;
        newHeight -= dy;
      }

      newWidth = Math.max(MIN_WIDTH, newWidth);
      newHeight = Math.max(MIN_HEIGHT, newHeight);

      setNodeSize({ width: newWidth, height: newHeight });
    };

    const handleMouseUp = () => {
      setIsResizing(false);
      resizeCornerRef.current = null;
    };

    document.addEventListener("mousemove", handleMouseMove);
    document.addEventListener("mouseup", handleMouseUp);

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isResizing, MIN_HEIGHT, MIN_WIDTH]);

  // Apply calculated min dimensions, with explicit size only if user has resized
  const sizeStyle: React.CSSProperties = {
    minWidth: MIN_WIDTH,
    minHeight: MIN_HEIGHT,
    ...(nodeSize.width > 0 && nodeSize.height > 0
      ? { width: nodeSize.width, height: nodeSize.height }
      : {})
  };

  const corners: Corner[] = ["bottom-right"];

  const handleViewLogs = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (globalShowLogsPopup) {
      // Collect logs from execution trace
      const logs = data.executionLogs || [];
      globalShowLogsPopup(id, data.displayName, logs);
    }
  };

  const handleRunNode = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onRunSelection?.(id);
  };

  const handleInterruptNode = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onInterrupt?.(id);
  };

  const handleClearNodeCache = (e: React.MouseEvent) => {
    e.stopPropagation();
    data.onClearCache?.(id);
  };

  return (
    <div
      ref={nodeRef}
      className={`blueprint-node ${statusClass} ${highlightClass}`}
      style={sizeStyle}
    >
      {/* Execution progress ring for running nodes */}
      {data.executionStatus === "running" && (
        <div className="node-execution-ring" />
      )}

      {corners.map((corner) => (
        <ResizeZone
          key={corner}
          corner={corner}
          isHovered={hoveredCorner === corner}
          onMouseEnter={() => setHoveredCorner(corner)}
          onMouseLeave={() => !isResizing && setHoveredCorner(null)}
          onMouseDown={(e) => handleResizeStart(corner, e)}
        />
      ))}

      <div className="node-header">
        <div className="node-title-section">
          <strong>{data.displayName}</strong>
          <span className="node-type-label">{data.nodeType}</span>
        </div>
        <div className="node-header-right">
          {data.executionStatus === "queued" && (
            <span className="node-status-chip queued">QUEUE</span>
          )}
          <button
            className="node-action-btn nodrag"
            onClick={handleViewLogs}
            title="View Logs"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" />
            </svg>
          </button>
          {(() => {
            const isActive = data.executionStatus === "running" || data.executionStatus === "queued";
            const wasInterrupted = data.executionStatus === "skipped" || data.executionStatus === "error";
            if (isActive) {
              return (
                <button
                  className="node-action-btn danger nodrag"
                  onClick={handleInterruptNode}
                  title="Interrupt node"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M6 19h12V5H6v14zm-2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2z" />
                  </svg>
                </button>
              );
            }
            if (data.last_outputs && !wasInterrupted) {
              return (
                <button
                  className="node-action-btn clear-cache-btn nodrag"
                  onClick={handleClearNodeCache}
                  title="Clear cached output"
                >
                  <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z" />
                  </svg>
                </button>
              );
            }
            return (
              <button
                className="node-action-btn run-btn nodrag"
                onClick={handleRunNode}
                title="Run from this node"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M8 5v14l11-7z" />
                </svg>
              </button>
            );
          })()}
          <button
            className="node-delete-btn nodrag"
            onClick={(e) => {
              e.stopPropagation();
              data.onDelete?.(id);
            }}
            title="Delete Node"
          >
            <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
              <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
            </svg>
          </button>
        </div>
      </div>

      <div className="node-ports">
        <div className="node-port-column">
          {data.input_ports.map((port, index) => (
            <div key={`in-${port}-${index}`} className="node-port node-port-input">
              <Handle
                type="target"
                position={Position.Left}
                id={port}
                className="node-handle"
              />
              <span>{port}</span>
            </div>
          ))}
        </div>
        <div className="node-port-column">
          {data.output_ports.map((port, index) => {
            const outputValue = data.last_outputs?.[port];
            const hasValue = outputValue !== undefined;
            return (
              <div key={`out-${port}-${index}`} className="node-port node-port-output">
                <span className="node-port-label">{port}</span>
                {hasValue && <OutputValue port={port} value={outputValue} />}
                <Handle
                  type="source"
                  position={Position.Right}
                  id={port}
                  className="node-handle"
                />
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

// Icons
const PlayIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M8 5v14l11-7z" />
  </svg>
);

const ChevronLeft = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z" />
  </svg>
);

const ChevronRight = () => (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
    <path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" />
  </svg>
);

const ConnectionIcon = ({ connected }: { connected: boolean }) => (
  <div className={`connection-indicator ${connected ? "connected" : "disconnected"}`} title={connected ? "WebSocket Connected" : "WebSocket Disconnected"}>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
      {connected ? (
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
      ) : (
        <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18c-4.42 0-8-3.58-8-8s3.58-8 8-8 8 3.58 8 8-3.58 8-8 8z" />
      )}
    </svg>
  </div>
);

const App = () => {
  const [nodeLibrary, setNodeLibrary] = useState<NodeTypeDefinition[]>([]);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<string[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [useStreaming] = useState(true);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const nodeIdRef = useRef(1);

  // Popup states
  const [valuePopup, setValuePopup] = useState<{ value: unknown; title: string } | null>(null);
  const [logsPopup, setLogsPopup] = useState<{ nodeId: string; nodeName: string; logs: string[] } | null>(null);
  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);

  // Smart Connect state
  const [connectStartParams, setConnectStartParams] = useState<{
    nodeId: string | null;
    handleId: string | null;
    handleType: "source" | "target" | null;
  } | null>(null);

  const [smartConnectMenu, setSmartConnectMenu] = useState<{
    isOpen: boolean;
    position: { x: number; y: number };
    flowPosition: { x: number; y: number };
    source: { nodeId: string; handleId: string; type: "source" | "target" } | null;
  }>({
    isOpen: false,
    position: { x: 0, y: 0 },
    flowPosition: { x: 0, y: 0 },
    source: null,
  });

  // Set global popup functions
  useEffect(() => {
    globalShowValuePopup = (value, title) => setValuePopup({ value, title });
    globalShowLogsPopup = (nodeId, nodeName, logs) => setLogsPopup({ nodeId, nodeName, logs });
    return () => {
      globalShowValuePopup = null;
      globalShowLogsPopup = null;
    };
  }, []);

  // Panel collapse states
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [rightPanelWidth, setRightPanelWidth] = useState(340);
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);

  // Right panel tab state
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>("inspector");
  
  // Header tab state
  const [headerTab, setHeaderTab] = useState<"graph-editor" | "outputs">("graph-editor");

  // Clipboard state for copy/paste (nodes only, no edges)
  const [clipboard, setClipboard] = useState<Node<BlueprintNodeData>[] | null>(null);

  // Custom selection box tracking for edge intersection selection
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionBox, setSelectionBox] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [previewEdgeIds, setPreviewEdgeIds] = useState<string[]>([]); // Edges highlighted during selection drag
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<BlueprintNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // Undo/Redo hook
  const { undo, redo, takeSnapshot, canUndo, canRedo } = useUndoRedo({
    nodes,
    edges,
    setNodes,
    setEdges,
  });

  // Use the execution hook
  const {
    isConnected,
    isRunning,
    error,
    trace,
    outputs,
    stats,
    levels,
    nodeStatuses,
    currentNodeId,
    progress,
    executionId,
    runGraph,
    runGraphSync,
  } = useGraphExecution();

  const nodeTypes = useMemo(() => ({ blueprint: BlueprintNode }), []);
  const edgeTypes = useMemo(() => ({ default: CustomEdge }), []);

  // Load node types
  useEffect(() => {
    fetch("/api/node-types")
      .then(async (response) => {
        if (!response.ok) throw new Error("Unable to load node registry.");
        const data: NodeTypeDefinition[] = await response.json();
        setNodeLibrary(data);
      })
      .catch(() => setNodeLibrary([]));
  }, []);

  // Handle panel resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizingLeft) {
        const newWidth = Math.min(Math.max(180, e.clientX), 400);
        setLeftPanelWidth(newWidth);
      }
      if (isResizingRight) {
        const newWidth = Math.min(Math.max(280, window.innerWidth - e.clientX), 600);
        setRightPanelWidth(newWidth);
      }
    };

    const handleMouseUp = () => {
      setIsResizingLeft(false);
      setIsResizingRight(false);
    };

    if (isResizingLeft || isResizingRight) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
  }, [isResizingLeft, isResizingRight]);

  // Update node execution states when nodeStatuses change
  useEffect(() => {
    if (nodeStatuses.size === 0 && !isRunning) return;

    setNodes((existing) =>
      existing.map((node) => {
        const status = nodeStatuses.get(node.id);
        const traceEntry = trace.find((t) => t.node_id === node.id);

        return {
          ...node,
          data: {
            ...node.data,
            executionStatus: status,
            executionDuration: traceEntry?.duration_ms,
            last_outputs: traceEntry?.outputs ?? node.data.last_outputs,
            executionLogs: traceEntry?.logs ?? node.data.executionLogs,
          },
        };
      })
    );
  }, [nodeStatuses, trace, isRunning, setNodes]);

  // Helper to get all dependent nodes (upstream dependencies)
  const getDependentNodes = useCallback((targetNodeIds: string[]): Set<string> => {
    const dependentIds = new Set<string>(targetNodeIds);
    const visited = new Set<string>();
    const queue = [...targetNodeIds];

    while (queue.length > 0) {
      const nodeId = queue.shift()!;
      if (visited.has(nodeId)) continue;
      visited.add(nodeId);

      // Find all edges that connect TO this node
      for (const edge of edges) {
        if (edge.target === nodeId && !dependentIds.has(edge.source)) {
          // Check if source node already has output (skip if it does)
          const sourceNode = nodes.find((n) => n.id === edge.source);
          if (!sourceNode?.data.last_outputs) {
            dependentIds.add(edge.source);
            queue.push(edge.source);
          }
        }
      }
    }

    return dependentIds;
  }, [edges, nodes]);

  // Update edges for running state (animated flow) - only for edges where source has no cached output
  useEffect(() => {
    setEdges((existing) =>
      existing.map((edge) => {
        // Find the source node to check if it has cached output
        const sourceNode = nodes.find((n) => n.id === edge.source);
        const sourceHasCachedOutput = Boolean(sourceNode?.data.last_outputs);

        // Edge should only animate if:
        // 1. Graph is running
        // 2. The target node is in the running set (needs this edge's data)
        // 3. The source node does NOT have cached output (data needs to be computed)
        const targetInRunningSet = runningNodeIds.has(edge.target);
        const shouldAnimate = isRunning && targetInRunningSet && !sourceHasCachedOutput;

        // Determine edge color
        let strokeColor = "#4a9eff"; // default
        if (isRunning && targetInRunningSet) {
          if (sourceHasCachedOutput) {
            // Source already computed - show green solid line
            strokeColor = "var(--accent-green)";
          } else if (nodeStatuses.get(edge.source) === "completed") {
            // Source just completed - show green
            strokeColor = "var(--accent-green)";
          } else {
            // Source still computing - show blue animated
            strokeColor = "var(--accent-blue)";
          }
        }

        return {
          ...edge,
          animated: shouldAnimate,
          style: {
            ...edge.style,
            stroke: strokeColor,
            strokeWidth: (isRunning && targetInRunningSet) ? 2.5 : 2,
          },
        };
      })
    );
  }, [isRunning, nodeStatuses, runningNodeIds, nodes, setEdges]);

  const handleSelectionChange = useCallback(
    (params: OnSelectionChangeParams) => {
      const nodeIds = (params.nodes ?? []).map((node) => node.id);
      const edgeIds = (params.edges ?? []).map((edge) => edge.id);
      setSelectedNodeIds(nodeIds);
      setSelectedEdgeIds(edgeIds);
      setSelectedNodeId(nodeIds[0] ?? null);
    },
    []
  );

  // Find edges that intersect with the selection box (in flow coordinates)
  const findIntersectingEdges = useCallback((
    box: { startX: number; startY: number; endX: number; endY: number },
    viewport: { x: number; y: number; zoom: number }
  ): string[] => {
    // Convert screen coordinates to flow coordinates
    const toFlowCoord = (screenX: number, screenY: number) => ({
      x: (screenX - viewport.x) / viewport.zoom,
      y: (screenY - viewport.y) / viewport.zoom,
    });

    const start = toFlowCoord(box.startX, box.startY);
    const end = toFlowCoord(box.endX, box.endY);

    const rx = Math.min(start.x, end.x);
    const ry = Math.min(start.y, end.y);
    const rw = Math.abs(end.x - start.x);
    const rh = Math.abs(end.y - start.y);

    // Skip if box is too small
    if (rw < 5 && rh < 5) return [];

    const intersectingEdgeIds: string[] = [];

    edges.forEach((edge) => {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);

      if (!sourceNode || !targetNode) return;

      // Calculate edge endpoints (approximate - right side of source, left side of target)
      const sourceX = sourceNode.position.x + (sourceNode.width || 160);
      const sourceY = sourceNode.position.y + (sourceNode.height || 80) / 2;
      const targetX = targetNode.position.x;
      const targetY = targetNode.position.y + (targetNode.height || 80) / 2;

      // Check if the bezier curve intersects the selection box
      if (bezierIntersectsRect(sourceX, sourceY, targetX, targetY, rx, ry, rw, rh)) {
        intersectingEdgeIds.push(edge.id);
      }
    });

    return intersectingEdgeIds;
  }, [edges, nodes]);

  // Get viewport from ReactFlow DOM
  const getViewport = useCallback(() => {
    const wrapper = reactFlowWrapper.current;
    if (wrapper) {
      const rfInstance = wrapper.querySelector('.react-flow__viewport');
      if (rfInstance) {
        const transform = rfInstance.getAttribute('style');
        const match = transform?.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/);
        if (match) {
          return {
            x: parseFloat(match[1]),
            y: parseFloat(match[2]),
            zoom: parseFloat(match[3]),
          };
        }
      }
    }
    return { x: 0, y: 0, zoom: 1 };
  }, []);

  // Update preview edges during selection drag
  const updatePreviewEdges = useCallback((box: { startX: number; startY: number; endX: number; endY: number }) => {
    const viewport = getViewport();
    const intersectingEdges = findIntersectingEdges(box, viewport);
    setPreviewEdgeIds(intersectingEdges);
  }, [getViewport, findIntersectingEdges]);

  // Handle selection end - finalize edge selection
  const handleSelectionEnd = useCallback(() => {
    if (previewEdgeIds.length > 0) {
      // Add preview edges to selection
      setSelectedEdgeIds((prev) => {
        const combined = new Set([...prev, ...previewEdgeIds]);
        return Array.from(combined);
      });
      // Also update the edges' selected state
      setEdges((eds) =>
        eds.map((e) => ({
          ...e,
          selected: previewEdgeIds.includes(e.id) || e.selected,
        }))
      );
    }
    setSelectionBox(null);
    setPreviewEdgeIds([]);
    setIsSelecting(false);
  }, [previewEdgeIds, setEdges]);

  useEffect(() => {
    if (selectedNodeId && !nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [nodes, selectedNodeId]);

  const updateNodeData = useCallback(
    (nodeId: string, updater: (data: BlueprintNodeData) => BlueprintNodeData) => {
      setNodes((nd) =>
        nd.map((node) => (node.id === nodeId ? { ...node, data: updater(node.data) } : node))
      );
    },
    [setNodes]
  );

  const handleParamChange = useCallback(
    (nodeId: string, param: string, value: string | number | boolean) =>
      updateNodeData(nodeId, (data) => ({
        ...data,
        params: { ...data.params, [param]: value },
      })),
    [updateNodeData]
  );

  const handleDeleteNode = useCallback((nodeId: string) => {
    setNodes((current) => current.filter((node) => node.id !== nodeId));
    setEdges((current) =>
      current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
    );
    if (selectedNodeId === nodeId) setSelectedNodeId(null);
    setSelectedNodeIds((current) => current.filter((id) => id !== nodeId));
  }, [selectedNodeId, setEdges, setNodes]);

  // Handle highlighting nodes from timeline/performance panel hover
  const handleHighlightNodes = useCallback((nodeIds: string[]) => {
    setHighlightedNodeIds(nodeIds);
  }, []);

  // Update nodes with highlighted state
  useEffect(() => {
    setNodes((existing) =>
      existing.map((node) => ({
        ...node,
        data: {
          ...node.data,
          isHighlighted: highlightedNodeIds.includes(node.id),
        },
      }))
    );
  }, [highlightedNodeIds, setNodes]);

  // Update edges with preview state during selection drag
  useEffect(() => {
    setEdges((existing) =>
      existing.map((edge) => ({
        ...edge,
        data: {
          ...edge.data,
          isPreview: previewEdgeIds.includes(edge.id),
        },
      }))
    );
  }, [previewEdgeIds, setEdges]);

  const buildGraphPayload = useCallback(
    (mode: "full" | "selection", targetNodes?: string[], extras?: { max_steps?: number }) => {
      const nodePayload = nodes.map((node) => ({
        id: node.id,
        type: node.data.nodeType,
        params: node.data.params,
      }));

      const linkPayload = edges
        .filter((edge): edge is typeof edge & { sourceHandle: string; targetHandle: string } =>
          Boolean(edge.sourceHandle) && Boolean(edge.targetHandle))
        .map((edge) => ({
          from_node: edge.source,
          from_port: edge.sourceHandle,
          to_node: edge.target,
          to_port: edge.targetHandle,
        }));

      const options: Record<string, unknown> = { mode };
      if (mode === "selection" && targetNodes?.length) {
        options.target_nodes = targetNodes;
      }
      if (extras?.max_steps != null) {
        options.max_steps = extras.max_steps;
      }

      return {
        graph: {
          nodes: nodePayload,
          links: linkPayload,
        },
        options,
      };
    },
    [edges, nodes]
  );

  const handleRunGraph = useCallback(
    async (mode: "full" | "selection", targetNodes?: string[], extras?: { max_steps?: number }) => {
      if (nodes.length === 0) return;

      // Determine which nodes will be running
      const runNodes = mode === "full"
        ? new Set(nodes.map((n) => n.id))
        : getDependentNodes(targetNodes || selectedNodeIds);

      setRunningNodeIds((prev) => {
        const merged = new Set(prev);
        runNodes.forEach((id) => merged.add(id));
        return merged;
      });

      const payload = buildGraphPayload(mode, targetNodes || (mode === "selection" ? selectedNodeIds : undefined), extras);

      // Clear previous execution states for running nodes only
      setNodes((existing) =>
        existing.map((node) => ({
          ...node,
          data: {
            ...node.data,
            executionStatus: runNodes.has(node.id) ? undefined : node.data.executionStatus,
            executionDuration: runNodes.has(node.id) ? undefined : node.data.executionDuration,
          },
        }))
      );

      const runIds = Array.from(runNodes);

      if (useStreaming && isConnected && !isRunning) {
        runGraph(payload, runIds);
      } else {
        try {
          await runGraphSync(payload, runIds);
        } catch {
          // Error handled by hook
        }
      }
    },
    [buildGraphPayload, getDependentNodes, isConnected, isRunning, nodes, runGraph, runGraphSync, selectedNodeIds, setNodes, useStreaming]
  );

  // Handle run selection from individual node
  const handleRunFromNode = useCallback((nodeId: string) => {
    handleRunGraph("selection", [nodeId]);
  }, [handleRunGraph]);

  // Handle clearing cache for a single node (also clears backend cache for that node type)
  const handleClearNodeCache = useCallback(async (nodeId: string) => {
    // Find the node to get its type
    const node = nodes.find((n) => n.id === nodeId);
    if (node) {
      // Clear backend cache for this node type
      try {
        await fetch(`/api/cache/clear/${encodeURIComponent(node.data.nodeType)}`, { method: "POST" });
      } catch (e) {
        console.error("Failed to clear backend cache for node type:", e);
      }
    }

    // Clear frontend state
    setNodes((existing) =>
      existing.map((n) =>
        n.id === nodeId
          ? {
            ...n,
            data: {
              ...n.data,
              last_outputs: undefined,
              executionStatus: undefined,
              executionDuration: undefined,
              executionLogs: [],
            },
          }
          : n
      )
    );
  }, [nodes, setNodes]);

  // Clear running node set when execution completes
  useEffect(() => {
    if (!isRunning) {
      setRunningNodeIds(new Set());
    }
  }, [isRunning]);

  // Trim running set as nodes finish to keep animation focused
  useEffect(() => {
    if (nodeStatuses.size === 0) return;
    setRunningNodeIds((prev) => {
      const next = new Set(prev);
      nodeStatuses.forEach((status, nodeId) => {
        if (status === "completed" || status === "skipped" || status === "error") {
          next.delete(nodeId);
        }
      });
      return next;
    });
  }, [nodeStatuses]);

  // Clear all cached outputs from nodes
  const handleClearCache = useCallback(() => {
    setNodes((existing) =>
      existing.map((node) => ({
        ...node,
        data: {
          ...node.data,
          last_outputs: undefined,
          executionStatus: undefined,
          executionDuration: undefined,
          executionLogs: [],
        },
      }))
    );
  }, [setNodes]);

  // Clear the backend execution cache
  const handleClearBackendCache = useCallback(async () => {
    try {
      const response = await fetch("/api/cache/clear", { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        console.log(`Cleared ${data.cleared} cached entries`);
        // Also clear frontend state
        handleClearCache();
      }
    } catch (e) {
      console.error("Failed to clear backend cache:", e);
    }
  }, [handleClearCache]);

  const handleInterruptAll = useCallback(async () => {
    if (!executionId) return;
    try {
      await fetch(`/api/executions/${executionId}/cancel`, { method: "POST" });
    } catch (e) {
      console.error("Failed to interrupt execution:", e);
    }
  }, [executionId]);

  const handleInterruptNode = useCallback(async (nodeId: string) => {
    if (!executionId) return;
    try {
      await fetch(`/api/executions/${executionId}/cancel/${nodeId}`, { method: "POST" });
    } catch (e) {
      console.error("Failed to interrupt node:", e);
    }
  }, [executionId]);

  // Delete selected nodes and edges
  const handleDeleteSelected = useCallback(() => {
    if (selectedNodeIds.length === 0 && selectedEdgeIds.length === 0) return;

    takeSnapshot();

    // Delete selected nodes
    if (selectedNodeIds.length > 0) {
      setNodes((current) => current.filter((node) => !selectedNodeIds.includes(node.id)));
    }

    // Delete selected edges AND edges connected to deleted nodes
    setEdges((current) =>
      current.filter(
        (edge) =>
          !selectedEdgeIds.includes(edge.id) &&
          !selectedNodeIds.includes(edge.source) &&
          !selectedNodeIds.includes(edge.target)
      )
    );

    setSelectedNodeIds([]);
    setSelectedEdgeIds([]);
    setSelectedNodeId(null);
  }, [selectedNodeIds, selectedEdgeIds, setNodes, setEdges]);

  // Duplicate selected nodes (no edges - edges can only be deleted)
  const handleDuplicateSelected = useCallback(() => {
    if (selectedNodeIds.length === 0) return;

    takeSnapshot();

    const selectedNodes = nodes.filter((node) => selectedNodeIds.includes(node.id));
    const newNodes: Node<BlueprintNodeData>[] = [];

    // Create new nodes with offset positions
    selectedNodes.forEach((node) => {
      const newId = `node-${nodeIdRef.current++}`;
      newNodes.push({
        ...node,
        id: newId,
        position: { x: node.position.x + 50, y: node.position.y + 50 },
        selected: false,
        data: {
          ...node.data,
          last_outputs: undefined,
          executionStatus: undefined,
          executionDuration: undefined,
          executionLogs: [],
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
        },
      });
    });

    setNodes((current) => [...current, ...newNodes]);

    // Select the new nodes
    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
  }, [selectedNodeIds, nodes, handleDeleteNode, handleRunFromNode, handleClearNodeCache, setNodes]);

  // Copy selected nodes to clipboard (no edges - edges can only be deleted)
  const handleCopy = useCallback(() => {
    if (selectedNodeIds.length === 0) return; // Only copy if nodes are selected
    const selectedNodes = nodes.filter((node) => selectedNodeIds.includes(node.id));
    setClipboard(selectedNodes);
  }, [selectedNodeIds, nodes]);

  // Paste from clipboard (nodes only, no edges)
  const handlePaste = useCallback(() => {
    if (!clipboard || clipboard.length === 0) return;

    takeSnapshot();

    const newNodes: Node<BlueprintNodeData>[] = [];

    clipboard.forEach((node) => {
      const newId = `node-${nodeIdRef.current++}`;
      newNodes.push({
        ...node,
        id: newId,
        position: { x: node.position.x + 80, y: node.position.y + 80 },
        selected: false,
        data: {
          ...node.data,
          last_outputs: undefined,
          executionStatus: undefined,
          executionDuration: undefined,
          executionLogs: [],
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
        },
      });
    });

    setNodes((current) => [...current, ...newNodes]);

    // Select the new nodes
    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
  }, [clipboard, handleDeleteNode, handleRunFromNode, handleClearNodeCache, setNodes]);

  // Select all nodes and edges
  const handleSelectAll = useCallback(() => {
    const allNodeIds = nodes.map((n) => n.id);
    const allEdgeIds = edges.map((e) => e.id);
    setSelectedNodeIds(allNodeIds);
    setSelectedEdgeIds(allEdgeIds);
    setSelectedNodeId(allNodeIds[0] ?? null);
    // Also update ReactFlow's internal selection state
    setNodes((nds) => nds.map((node) => ({ ...node, selected: true })));
    setEdges((eds) => eds.map((edge) => ({ ...edge, selected: true })));
  }, [nodes, edges, setNodes, setEdges]);

  // Keyboard shortcuts
  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      // Don't trigger shortcuts when typing in inputs
      const target = event.target as HTMLElement;
      if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
        return;
      }

      const isCtrlOrCmd = event.ctrlKey || event.metaKey;

      // Delete selected nodes and edges
      if (event.key === "Delete" || event.key === "Backspace") {
        event.preventDefault();
        handleDeleteSelected();
        return;
      }

      // Ctrl+A - Select all
      if (isCtrlOrCmd && event.key === "a") {
        event.preventDefault();
        handleSelectAll();
        return;
      }

      // Ctrl+D - Duplicate (only for nodes)
      if (isCtrlOrCmd && event.key === "d") {
        event.preventDefault();
        if (selectedNodeIds.length > 0) {
          handleDuplicateSelected();
        }
        return;
      }

      // Ctrl+C - Copy (only for nodes)
      if (isCtrlOrCmd && event.key === "c") {
        event.preventDefault();
        if (selectedNodeIds.length > 0) {
          handleCopy();
        }
        return;
      }

      // Ctrl+V - Paste
      if (isCtrlOrCmd && event.key === "v") {
        event.preventDefault();
        handlePaste();
        return;
      }

      // Ctrl+Z - Undo
      if (isCtrlOrCmd && !event.shiftKey && event.key === "z") {
        event.preventDefault();
        undo();
        return;
      }

      // Ctrl+Shift+Z or Ctrl+Y - Redo
      if ((isCtrlOrCmd && event.shiftKey && event.key === "z") || (isCtrlOrCmd && event.key === "y")) {
        event.preventDefault();
        redo();
        return;
      }
    };

    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [handleDeleteSelected, handleSelectAll, handleDuplicateSelected, handleCopy, handlePaste, selectedNodeIds]);

  const handleAddNode = useCallback(
    (nodeType: NodeTypeDefinition) => {
      takeSnapshot();
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }
      const id = `node-${nodeIdRef.current++}`;
      const position = { x: 120 + nodes.length * 36, y: 80 + nodes.length * 32 };

      // Calculate initial size based on ports (matches MIN_WIDTH/MIN_HEIGHT in BlueprintNode)
      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const initialWidth = 200;
      const initialHeight = 64 + maxPorts * 26;

      const payload: Node<BlueprintNodeData> = {
        id,
        type: "blueprint",
        position,
        data: {
          displayName: nodeType.display_name,
          nodeType: nodeType.node_type,
          description: nodeType.description,
          input_ports: nodeType.input_ports,
          output_ports: nodeType.output_ports,
          params,
          breakpoint: false,
          metadata: nodeType,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
          width: initialWidth,
          height: initialHeight,
          executionLogs: [],
        },
      };
      setNodes((existing) => existing.concat(payload));
    },
    [handleDeleteNode, handleRunFromNode, handleClearNodeCache, nodes.length, setNodes]
  );

  // Update existing nodes with the run handler
  useEffect(() => {
    setNodes((existing) =>
      existing.map((node) => ({
        ...node,
        data: {
          ...node.data,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
        },
      }))
    );
  }, [handleDeleteNode, handleRunFromNode, handleClearNodeCache, handleInterruptNode, setNodes]);

  const graphStats = useMemo(
    () => ({
      nodes: nodes.length,
      edges: edges.length,
      selection: selectedNodeIds.length,
    }),
    [edges.length, nodes, selectedNodeIds.length]
  );

  const handleConnect = useCallback(
    (connection: Parameters<typeof addEdge>[0]) => {
      if (!connection.sourceHandle || !connection.targetHandle) return;

      // Check for duplicate edges (same source, target, sourceHandle, targetHandle)
      const isDuplicate = edges.some(
        (edge) =>
          edge.source === connection.source &&
          edge.target === connection.target &&
          edge.sourceHandle === connection.sourceHandle &&
          edge.targetHandle === connection.targetHandle
      );

      if (isDuplicate) {
        return; // Don't add duplicate edge
      }

      takeSnapshot();

      setEdges((existing) => {
        // Remove any existing edge that connects to the same target handle
        const filtered = existing.filter(
          (edge) =>
            !(edge.target === connection.target && edge.targetHandle === connection.targetHandle)
        );

        return addEdge(
          {
            ...connection,
            type: "default",
            animated: false,
            style: { stroke: "#4a9eff", strokeWidth: 2 },
          },
          filtered
        );
      });
    },
    [edges, setEdges, takeSnapshot]
  );

  // Helper to calculate handle position for smart connect line
  const getHandlePosition = useCallback((nodeId: string, handleId: string, type: "source" | "target") => {
    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return null;

    const isInput = type === "target";
    const ports = isInput ? node.data.input_ports : node.data.output_ports;
    const index = ports.indexOf(handleId);

    if (index === -1) return null;

    // Matches BlueprintNode layout constants
    // Header ~50px (8px pad + ~27px content + 6px pad + 1px border + 8px margin)
    // Each port row: 20px height + 6px gap = 26px stride
    // Handle is centered in row (+10px)
    const yOffset = 50 + index * 26 + 10;

    // Use measured width if available, otherwise fallback
    const nodeWidth = node.width ?? 200;

    return {
      x: node.position.x + (isInput ? 0 : nodeWidth),
      y: node.position.y + yOffset,
    };
  }, [nodes]);

  const onConnectStart = useCallback((_: unknown, { nodeId, handleId, handleType }: { nodeId: string | null; handleId: string | null; handleType: "source" | "target" | null }) => {
    setConnectStartParams({ nodeId, handleId, handleType });
  }, []);

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent) => {
      const target = event.target as HTMLElement;
      const isPane = target.classList.contains("react-flow__pane");

      if (isPane && connectStartParams?.nodeId && connectStartParams?.handleId && reactFlowInstance) {
        const { clientX, clientY } = "changedTouches" in event ? event.changedTouches[0] : (event as MouseEvent);

        const position = reactFlowInstance.screenToFlowPosition({
          x: clientX,
          y: clientY,
        });

        setSmartConnectMenu({
          isOpen: true,
          position: { x: clientX, y: clientY },
          flowPosition: position,
          source: {
            nodeId: connectStartParams.nodeId,
            handleId: connectStartParams.handleId,
            type: connectStartParams.handleType || "source",
          },
        });
      }

      setConnectStartParams(null);
    },
    [connectStartParams, reactFlowInstance]
  );

  const handleSmartConnectSelect = useCallback(
    (nodeType: NodeTypeDefinition) => {
      if (!smartConnectMenu.source) return;

      takeSnapshot();

      const { flowPosition, source } = smartConnectMenu;
      const newId = `node-${nodeIdRef.current++}`;

      // Create new node
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }

      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const initialWidth = 200;
      const initialHeight = 64 + maxPorts * 26;

      // Calculate position to align the connecting handle with the drop location
      let xOffset = 0;
      let yOffset = 0;

      // Header ~50px, Port stride ~26px, Handle center +10px
      // We connect to the first port (index 0) by default
      const portYOffset = 50 + 0 * 26 + 10;

      if (source.type === "source") {
        // Dragging from Source (Output) -> Connect to New Node's Input (Left side)
        xOffset = 0;
        yOffset = portYOffset;
      } else {
        // Dragging from Target (Input) -> Connect to New Node's Output (Right side)
        xOffset = initialWidth;
        yOffset = portYOffset;
      }

      const newNode: Node<BlueprintNodeData> = {
        id: newId,
        type: "blueprint",
        position: { x: flowPosition.x - xOffset, y: flowPosition.y - yOffset },
        data: {
          displayName: nodeType.display_name,
          nodeType: nodeType.node_type,
          description: nodeType.description,
          input_ports: nodeType.input_ports,
          output_ports: nodeType.output_ports,
          params,
          breakpoint: false,
          metadata: nodeType,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          width: initialWidth,
          height: initialHeight,
          executionLogs: [],
          onInterrupt: handleInterruptNode,
        },
      };

      setNodes((nds) => nds.concat(newNode));

      // Create connection
      // If dragging from source (output), connect to first input of new node
      // If dragging from target (input), connect from first output of new node
      let sourceId, sourceHandle, targetId, targetHandle;

      if (source.type === "source") {
        sourceId = source.nodeId;
        sourceHandle = source.handleId;
        targetId = newId;
        targetHandle = nodeType.input_ports[0]; // Connect to first input
      } else {
        sourceId = newId;
        sourceHandle = nodeType.output_ports[0]; // Connect from first output
        targetId = source.nodeId;
        targetHandle = source.handleId;
      }

      if (sourceHandle && targetHandle) {
        setEdges((eds) =>
          addEdge(
            {
              source: sourceId,
              sourceHandle: sourceHandle,
              target: targetId,
              targetHandle: targetHandle,
              type: "default",
              animated: false,
              style: { stroke: "#4a9eff", strokeWidth: 2 },
            },
            eds
          )
        );
      }

      setSmartConnectMenu((prev) => ({ ...prev, isOpen: false }));
    },
    [smartConnectMenu, handleDeleteNode, handleRunFromNode, handleClearNodeCache, setNodes, setEdges]
  );

  const selectedNodes = useMemo(
    () => nodes.filter((node) => selectedNodeIds.includes(node.id)),
    [nodes, selectedNodeIds]
  );

  const actualLeftWidth = leftPanelCollapsed ? 0 : leftPanelWidth;
  const actualRightWidth = rightPanelCollapsed ? 0 : rightPanelWidth;

  // Track selection box via mouse events
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Only track left mouse button for selection
    if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      const target = e.target as HTMLElement;
      // Only start selection on the pane background
      if (target.classList.contains('react-flow__pane')) {
        const rect = reactFlowWrapper.current?.getBoundingClientRect();
        if (rect) {
          setIsSelecting(true);
          setSelectionBox({
            startX: e.clientX - rect.left,
            startY: e.clientY - rect.top,
            endX: e.clientX - rect.left,
            endY: e.clientY - rect.top,
          });
        }
      }
    }
  }, []);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isSelecting && selectionBox) {
      const rect = reactFlowWrapper.current?.getBoundingClientRect();
      if (rect) {
        const newBox = {
          ...selectionBox,
          endX: e.clientX - rect.left,
          endY: e.clientY - rect.top,
        };
        setSelectionBox(newBox);
        // Update preview edges in real-time
        updatePreviewEdges(newBox);
      }
    }
  }, [isSelecting, selectionBox, updatePreviewEdges]);

  const handleMouseUp = useCallback(() => {
    if (isSelecting) {
      handleSelectionEnd();
    }
  }, [isSelecting, handleSelectionEnd]);

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const typeData = event.dataTransfer.getData("application/reactflow");
      if (typeof typeData === "undefined" || !typeData) {
        return;
      }

      const nodeType: NodeTypeDefinition = JSON.parse(typeData);

      // check if the dropped element is valid
      if (typeof nodeType === "undefined" || !nodeType) {
        return;
      }

      const position = reactFlowInstance?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      if (!position) return;

      takeSnapshot();

      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }

      const id = `node-${nodeIdRef.current++}`;

      // Calculate initial size based on ports
      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const initialWidth = 200;
      const initialHeight = 64 + maxPorts * 26;

      const newNode: Node<BlueprintNodeData> = {
        id,
        type: "blueprint",
        position,
        data: {
          displayName: nodeType.display_name,
          nodeType: nodeType.node_type,
          description: nodeType.description,
          input_ports: nodeType.input_ports,
          output_ports: nodeType.output_ports,
          params,
          breakpoint: false,
          metadata: nodeType,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          width: initialWidth,
          height: initialHeight,
          executionLogs: [],
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance, setNodes, handleDeleteNode, handleRunFromNode, handleClearNodeCache]
  );

  return (
    <ReactFlowProvider>
      <div className="app-shell">
        {headerTab === "graph-editor" ? (
          <div
            className="reactflow-fullpage"
            ref={reactFlowWrapper}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onInit={setReactFlowInstance}
            onConnect={handleConnect}
            onConnectStart={onConnectStart}
            onConnectEnd={onConnectEnd}
            onNodeDragStart={() => takeSnapshot()}
            onSelectionDragStart={() => takeSnapshot()}
            onSelectionChange={handleSelectionChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            connectionLineStyle={{ stroke: "#4a9eff" }}
            attributionPosition="bottom-left"
            selectionMode={SelectionMode.Partial}
            selectionOnDrag
            panOnDrag={[1, 2]}
            selectNodesOnDrag
            edgesFocusable
            edgesUpdatable
            elementsSelectable
          >
            <Background gap={20} size={1} color="rgba(255,255,255,0.03)" />
            <Controls
              showZoom
              showFitView
              showInteractive={false}
              position="bottom-left"
              style={{ left: actualLeftWidth }}
            />
            <MiniMap
              nodeColor={(node) => {
                const status = nodeStatuses.get(node.id);
                if (status === "running") return "#58a6ff";
                if (status === "completed") return "#3fb950";
                if (status === "error") return "#f85149";
                return "#4a9eff";
              }}
              maskColor="rgba(0,0,0,0.8)"
              style={{
                backgroundColor: "rgba(20,25,35,0.9)",
                right: actualRightWidth,
              }}
            />
          </ReactFlow>
        </div>
        ) : (
          <div className="outputs-fullpage">
            <OutputsView nodes={nodes} outputs={outputs} />
          </div>
        )}

        <header className="overlay-header">
          <div className="header-left">
            <div className="header-tabs">
              <button
                type="button"
                className={`header-tab ${headerTab === "graph-editor" ? "active" : ""}`}
                onClick={() => setHeaderTab("graph-editor")}
              >
                Graph Editor
              </button>
              <button
                type="button"
                className={`header-tab ${headerTab === "outputs" ? "active" : ""}`}
                onClick={() => setHeaderTab("outputs")}
              >
                Outputs
              </button>
            </div>
            {headerTab === "graph-editor" && isRunning && (
              <div className="header-stats">
                <span className="stat-badge running">
                  <span className="pulse-dot" />
                  {Math.round(progress * 100)}%
                </span>
              </div>
            )}
          </div>
          <div className="header-controls">
            <ConnectionIcon connected={isConnected} />
            <button
              className="icon-btn primary"
              onClick={() => handleRunGraph("full")}
              disabled={nodes.length === 0}
              title="Run Graph"
            >
              <PlayIcon />
              {isRunning && <span className="btn-spinner" />}
            </button>
            <button
              className="icon-btn danger"
              onClick={handleInterruptAll}
              disabled={!isRunning || !executionId}
              title="Interrupt all running nodes"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6 19h12V5H6v14zm-2 2h16c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2H4c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2z" />
              </svg>
            </button>
            <button
              className="icon-btn clear-cache-btn"
              onClick={handleClearBackendCache}
              disabled={isRunning}
              title="Clear Backend Cache"
            >
              <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
                <path d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14M6 19a2 2 0 0 0 2 2h8a2 2 0 0 0 2-2V7H6v12z" />
              </svg>
            </button>
            {error && <span className="error-indicator" title={error}>!</span>}
          </div>
        </header>

        <aside
          className={`side-panel left-panel ${leftPanelCollapsed ? "collapsed" : ""}`}
          style={{ width: leftPanelCollapsed ? 0 : leftPanelWidth }}
        >
          {!leftPanelCollapsed && (
            <>
              <NodePalette nodeTypes={nodeLibrary} onAddNode={handleAddNode} />
              <div
                className="resize-handle right"
                onMouseDown={() => setIsResizingLeft(true)}
              />
            </>
          )}
        </aside>

        <button
          className="panel-collapse-btn left"
          style={{ left: leftPanelCollapsed ? 0 : leftPanelWidth }}
          onClick={() => setLeftPanelCollapsed(!leftPanelCollapsed)}
          title={leftPanelCollapsed ? "Expand Nodes" : "Collapse Nodes"}
        >
          {leftPanelCollapsed ? <ChevronRight /> : <ChevronLeft />}
        </button>

        <aside
          className={`side-panel right-panel ${rightPanelCollapsed ? "collapsed" : ""}`}
          style={{ width: rightPanelCollapsed ? 0 : rightPanelWidth }}
        >
          {!rightPanelCollapsed && (
            <>
              <div
                className="resize-handle left"
                onMouseDown={() => setIsResizingRight(true)}
              />
              <div className="right-panel-content">
                {/* Right panel tabs */}
                <div className="right-panel-tabs">
                  <button
                    type="button"
                    className={`right-panel-tab ${rightPanelTab === "inspector" ? "active" : ""}`}
                    onClick={() => setRightPanelTab("inspector")}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
                    </svg>
                    Inspector {selectedNodeIds.length > 0 && `(${selectedNodeIds.length})`}
                  </button>
                  <button
                    type="button"
                    className={`right-panel-tab ${rightPanelTab === "execution" ? "active" : ""}`}
                    onClick={() => setRightPanelTab("execution")}
                  >
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                    Execution {trace.length > 0 && `(${trace.length})`}
                  </button>
                </div>

                {/* Multi-selection toolbar */}
                {(selectedNodeIds.length > 1 || selectedEdgeIds.length > 0) && (
                  <div className="multi-select-toolbar">
                    <span className="selection-count">
                      {selectedNodeIds.length > 0 && `${selectedNodeIds.length} node${selectedNodeIds.length !== 1 ? "s" : ""}`}
                      {selectedNodeIds.length > 0 && selectedEdgeIds.length > 0 && ", "}
                      {selectedEdgeIds.length > 0 && `${selectedEdgeIds.length} edge${selectedEdgeIds.length !== 1 ? "s" : ""}`}
                      {" "}selected
                    </span>
                    <div className="toolbar-actions">
                      {/* Only show duplicate/copy for nodes */}
                      {selectedNodeIds.length > 0 && (
                        <>
                          <button
                            type="button"
                            className="toolbar-btn"
                            onClick={handleDuplicateSelected}
                            title="Duplicate (Ctrl+D)"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z" />
                            </svg>
                            Duplicate
                          </button>
                          <button
                            type="button"
                            className="toolbar-btn"
                            onClick={handleCopy}
                            title="Copy (Ctrl+C)"
                          >
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z" />
                            </svg>
                            Copy
                          </button>
                        </>
                      )}
                      <button
                        type="button"
                        className="toolbar-btn danger"
                        onClick={handleDeleteSelected}
                        title="Delete (Del)"
                      >
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                          <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
                        </svg>
                        Delete
                      </button>
                    </div>
                  </div>
                )}

                {/* Tab content */}
                <div className="right-panel-tab-content">
                  {rightPanelTab === "inspector" && (
                    <NodeInspector
                      nodes={selectedNodes}
                      onParamChange={handleParamChange}
                      onDelete={handleDeleteNode}
                      onDuplicate={(nodeId) => {
                        setSelectedNodeIds([nodeId]);
                        setSelectedNodeId(nodeId);
                        setTimeout(() => handleDuplicateSelected(), 0);
                      }}
                    />
                  )}
                  {rightPanelTab === "execution" && (
                    <LogPanel
                      trace={trace}
                      outputs={outputs}
                      error={error}
                      stats={stats}
                      levels={levels}
                      isRunning={isRunning}
                      currentNodeId={currentNodeId}
                      nodeStatuses={nodeStatuses}
                      progress={progress}
                      onHighlightNodes={handleHighlightNodes}
                    />
                  )}
                </div>
              </div>
            </>
          )}
        </aside>

        <button
          className="panel-collapse-btn right"
          style={{ right: rightPanelCollapsed ? 0 : rightPanelWidth }}
          onClick={() => setRightPanelCollapsed(!rightPanelCollapsed)}
          title={rightPanelCollapsed ? "Expand Logs" : "Collapse Logs"}
        >
          {rightPanelCollapsed ? <ChevronLeft /> : <ChevronRight />}
        </button>

        {/* Value Popup */}
        {valuePopup && (
          <ValuePopup
            value={valuePopup.value}
            title={valuePopup.title}
            onClose={() => setValuePopup(null)}
          />
        )}

        {/* Logs Popup */}
        {logsPopup && (
          <LogsPopup
            nodeId={logsPopup.nodeId}
            nodeName={logsPopup.nodeName}
            logs={logsPopup.logs}
            onClose={() => setLogsPopup(null)}
          />
        )}

        {/* Smart Connect Line */}
        {smartConnectMenu.isOpen && smartConnectMenu.source && (
          <svg
            style={{
              position: "absolute",
              top: 0,
              left: 0,
              width: "100%",
              height: "100%",
              pointerEvents: "none",
              zIndex: 999,
              overflow: "visible",
            }}
          >
            {(() => {
              const startFlow = getHandlePosition(
                smartConnectMenu.source.nodeId,
                smartConnectMenu.source.handleId,
                smartConnectMenu.source.type
              );
              if (!startFlow || !reactFlowInstance) return null;

              // Convert start point to screen coordinates
              const start = reactFlowInstance.flowToScreenPosition(startFlow);
              const end = smartConnectMenu.position;

              const isSource = smartConnectMenu.source.type === "source";
              const startX = start.x;
              const startY = start.y;
              const endX = end.x;
              const endY = end.y;

              const dist = Math.abs(endX - startX) * 0.5;
              const cp1x = isSource ? startX + dist : startX - dist;
              const cp1y = startY;
              const cp2x = isSource ? endX - dist : endX + dist;
              const cp2y = endY;

              const path = `M ${startX} ${startY} C ${cp1x} ${cp1y} ${cp2x} ${cp2y} ${endX} ${endY}`;

              return (
                <path
                  d={path}
                  stroke="#4a9eff"
                  strokeWidth="2"
                  fill="none"
                  strokeDasharray="5,5"
                  className="smart-connect-line"
                />
              );
            })()}
          </svg>
        )}

        {/* Smart Connect Modal */}
        <SmartConnectModal
          isOpen={smartConnectMenu.isOpen}
          position={smartConnectMenu.position}
          onClose={() => setSmartConnectMenu((prev) => ({ ...prev, isOpen: false }))}
          onSelect={handleSmartConnectSelect}
          nodeTypes={nodeLibrary}
          sourceHandleType={smartConnectMenu.source?.type}
        />
      </div>
    </ReactFlowProvider >
  );
};

export default App;
