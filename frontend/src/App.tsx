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
} from "reactflow";
import "reactflow/dist/style.css";

import LogPanel from "./components/LogPanel";
import NodeInspector from "./components/NodeInspector";
import NodePalette from "./components/NodePalette";
import { useGraphExecution } from "./hooks/useGraphExecution";
import {
  BlueprintNodeData,
  NodeExecutionStatus,
  NodeTypeDefinition,
} from "./types";

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

// Custom Edge with delete button
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

  return (
    <g
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
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
        style={style}
        markerEnd={markerEnd}
      />
      {isHovered && (
        <g
          transform={`translate(${labelX - 7}, ${labelY - 7})`}
          onClick={handleDeleteEdge}
          style={{ cursor: "pointer" }}
        >
          <circle
            r="7"
            cx="7"
            cy="7"
            fill="var(--accent-blue)"
          />
          <path
            d="M4.5 4.5L9.5 9.5M9.5 4.5L4.5 9.5"
            stroke="white"
            strokeWidth="1.5"
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
  const MIN_WIDTH = 160;
  const MIN_HEIGHT = 52 + maxPorts * 24;

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
          {data.last_outputs ? (
            <button
              className="node-action-btn clear-cache-btn nodrag"
              onClick={handleClearNodeCache}
              title="Clear cached output"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.47 2 2 6.47 2 12s4.47 10 10 10 10-4.47 10-10S17.53 2 12 2zm5 13.59L15.59 17 12 13.41 8.41 17 7 15.59 10.59 12 7 8.41 8.41 7 12 10.59 15.59 7 17 8.41 13.41 12 17 15.59z" />
              </svg>
            </button>
          ) : (
            <button
              className="node-action-btn run-btn nodrag"
              onClick={handleRunNode}
              title="Run from this node"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M8 5v14l11-7z" />
              </svg>
            </button>
          )}
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

const ClearCacheIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M19 4h-3.5l-1-1h-5l-1 1H5v2h14V4zM6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM8 9h8v10H8V9z" />
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
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [useStreaming] = useState(true);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const nodeIdRef = useRef(1);

  // Popup states
  const [valuePopup, setValuePopup] = useState<{ value: unknown; title: string } | null>(null);
  const [logsPopup, setLogsPopup] = useState<{ nodeId: string; nodeName: string; logs: string[] } | null>(null);

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

  const [nodes, setNodes, onNodesChange] = useNodesState<BlueprintNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

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
      setSelectedNodeIds(nodeIds);
      setSelectedNodeId(nodeIds[0] ?? null);
    },
    []
  );

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
      if (isRunning || nodes.length === 0) return;

      // Determine which nodes will be running
      const runNodes = mode === "full" 
        ? new Set(nodes.map((n) => n.id))
        : getDependentNodes(targetNodes || selectedNodeIds);
      
      setRunningNodeIds(runNodes);

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

      if (useStreaming && isConnected) {
        runGraph(payload);
      } else {
        try {
          await runGraphSync(payload);
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

  // Handle clearing cache for a single node
  const handleClearNodeCache = useCallback((nodeId: string) => {
    setNodes((existing) =>
      existing.map((node) =>
        node.id === nodeId
          ? {
              ...node,
              data: {
                ...node.data,
                last_outputs: undefined,
                executionStatus: undefined,
                executionDuration: undefined,
                executionLogs: [],
              },
            }
          : node
      )
    );
  }, [setNodes]);

  // Clear running node set when execution completes
  useEffect(() => {
    if (!isRunning) {
      setRunningNodeIds(new Set());
    }
  }, [isRunning]);

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

  const handleAddNode = useCallback(
    (nodeType: NodeTypeDefinition) => {
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }
      const id = `node-${nodeIdRef.current++}`;
      const position = { x: 120 + nodes.length * 36, y: 80 + nodes.length * 32 };
      
      // Calculate initial size based on ports (matches MIN_WIDTH/MIN_HEIGHT in BlueprintNode)
      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const initialWidth = 160;
      const initialHeight = 52 + maxPorts * 24;
      
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
        },
      }))
    );
  }, [handleDeleteNode, handleRunFromNode, handleClearNodeCache, setNodes]);

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

      setEdges((existing) =>
        addEdge(
          {
            ...connection,
            type: "default",
            animated: false,
            style: { stroke: "#4a9eff", strokeWidth: 2 },
          },
          existing
        )
      );
    },
    [edges, setEdges]
  );

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId),
    [nodes, selectedNodeId]
  );

  const actualLeftWidth = leftPanelCollapsed ? 0 : leftPanelWidth;
  const actualRightWidth = rightPanelCollapsed ? 0 : rightPanelWidth;

  return (
    <ReactFlowProvider>
      <div className="app-shell">
        <div className="reactflow-fullpage">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={handleConnect}
            onSelectionChange={handleSelectionChange}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            fitView
            connectionLineStyle={{ stroke: "#4a9eff" }}
            attributionPosition="bottom-left"
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
          <div 
            className="editor-top-controls"
            style={{ right: actualRightWidth + 10 }}
          >
            <button
              className="editor-control-btn"
              onClick={handleClearCache}
              disabled={isRunning}
              title="Clear Cached Outputs"
            >
              <ClearCacheIcon />
            </button>
          </div>
        </div>

        <header className="overlay-header">
          <div className="header-left">
            <h1>LiGuard Graph</h1>
            <div className="header-stats">
              <span className="stat-badge">{graphStats.nodes} nodes</span>
              <span className="stat-badge">{graphStats.edges} edges</span>
              {isRunning && (
                <span className="stat-badge running">
                  <span className="pulse-dot" />
                  {Math.round(progress * 100)}%
                </span>
              )}
            </div>
          </div>
          <div className="header-controls">
            <ConnectionIcon connected={isConnected} />
            <button
              className="icon-btn primary"
              onClick={() => handleRunGraph("full")}
              disabled={isRunning || nodes.length === 0}
              title="Run Graph"
            >
              <PlayIcon />
              {isRunning && <span className="btn-spinner" />}
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
                <NodeInspector
                  node={selectedNode}
                  onParamChange={handleParamChange}
                />
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
      </div>
    </ReactFlowProvider>
  );
};

export default App;
