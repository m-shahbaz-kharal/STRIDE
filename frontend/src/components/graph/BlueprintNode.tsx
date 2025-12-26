import React, { useCallback, useEffect, useRef, useState } from "react";
import { Handle, NodeProps, Position, useReactFlow, useStore } from "reactflow";

import { usePopups } from "../../context/PopupContext";
import {
  BlueprintNodeData,
  NodeExecutionStatus,
} from "../../types";
import {
  MIN_NODE_WIDTH,
  computeNodeDimensions,
  formatPortTypeLabel,
  getExecutionStatusClass,
  getPortTypeColor,
} from "../../graph/utils";

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

  const zoneSize = 16;
  const zoneOffset = corner === "bottom-right" ? `-${zoneSize - 4}px` : "-2px";

  return (
    <div
      className={`resize-zone nodrag ${corner} ${isHovered ? "hovered" : ""}`}
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
    />
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
  const edges = useStore((state) => state.edges);
  const { showLogsPopup } = usePopups();

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
    zoomRef.current = getZoom();
    setNodeSize({ width, height });
    setIsResizing(true);
  }, [getZoom]);

  const extraInputRows = data.nodeType === "core.container.make_array" ? 1 : 0;
  const maxPorts = Math.max(data.input_ports.length + extraInputRows, data.output_ports.length);
  const MIN_HEIGHT = computeNodeDimensions(maxPorts).height;
  const inputPortTypes = data.input_port_types || data.metadata?.input_port_types || {};
  const outputPortTypes = data.output_port_types || data.metadata?.output_port_types || {};

  const resolvePortType = useCallback(
    (port: string, direction: "input" | "output") => {
      const map = direction === "input" ? inputPortTypes : outputPortTypes;
      return map?.[port] || "any";
    },
    [inputPortTypes, outputPortTypes]
  );

  const getTypeKind = useCallback((portType: unknown): string => {
    if (!portType) return "any";
    if (typeof portType === "string") return portType.toLowerCase();
    if (typeof portType === "object" && "kind" in (portType as { kind?: string })) {
      return (portType as { kind?: string }).kind || "any";
    }
    return "any";
  }, []);

  const isInputConnected = useCallback(
    (port: string) =>
      edges.some((edge) => edge.target === id && edge.targetHandle === port),
    [edges, id]
  );

  const getInputDefault = useCallback(
    (port: string) => data.metadata?.inputs?.find((input) => input.name === port)?.default,
    [data.metadata?.inputs]
  );

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const corner = resizeCornerRef.current;
      if (!corner) return;

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

      newWidth = Math.max(MIN_NODE_WIDTH, newWidth);
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
  }, [isResizing, MIN_HEIGHT]);

  const sizeStyle: React.CSSProperties = {
    minWidth: MIN_NODE_WIDTH,
    minHeight: MIN_HEIGHT,
    ...(nodeSize.width > 0 && nodeSize.height > 0
      ? { width: nodeSize.width, height: nodeSize.height }
      : {})
  };

  const corners: Corner[] = ["bottom-right"];

  const handleViewLogs = (e: React.MouseEvent) => {
    e.stopPropagation();
    const logs = data.executionLogs || [];
    showLogsPopup(id, data.displayName, logs);
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

  const renderStatusChip = (status?: NodeExecutionStatus) => {
    if (status === "queued") return <span className="node-status-chip queued">QUEUE</span>;
    return null;
  };

  return (
    <div
      ref={nodeRef}
      className={`blueprint-node ${statusClass} ${highlightClass}`}
      style={sizeStyle}
    >
      {data.executionStatus === "running" && <div className="node-execution-ring" />}

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
          <div className="node-name-tooltip" data-tooltip={data.nodeType}>
            <strong>{data.displayName}</strong>
          </div>
        </div>
        <div className="node-header-right">
          {renderStatusChip(data.executionStatus)}
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
                    <rect x="6" y="6" width="12" height="12" rx="1.5" />
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
                  <svg width="12" height="12" viewBox="0 0 48 48" fill="none">
                    <g transform="translate(4 4) scale(0.8333)">
                      <path d="M44.7818 24.1702L31.918 7.09938L14.1348 20.5L27.5 37L30.8556 34.6644L44.7818 24.1702Z" fill="currentColor" stroke="currentColor" strokeWidth="4.30201" strokeLinejoin="round" />
                      <path d="M27.4998 37L23.6613 40.0748L13.0978 40.074L10.4973 36.6231L4.06543 28.0876L14.4998 20.2248" stroke="currentColor" strokeWidth="4.30201" strokeLinejoin="round" />
                      <path d="M13.2056 40.0721L44.5653 40.072" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
                    </g>
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
          {data.input_ports.map((port, index) => {
            const portType = resolvePortType(port, "input");
            const portKind = getTypeKind(portType);
            const isControl = portKind === "control";
            const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
            const color = getPortTypeColor(portType);
            const handleStyle: React.CSSProperties = { ["--handle-color" as string]: color };
            const isHighlighted = data.highlightedPort?.port === port && data.highlightedPort?.direction === "input";
            const isConnected = isInputConnected(port);
            const inputValue = data.inputValues?.[port];
            const defaultValue = getInputDefault(port);
            const hasInputValue = Object.prototype.hasOwnProperty.call(data.inputValues ?? {}, port);
            const resolvedValue = hasInputValue ? inputValue : defaultValue;
            const placeholderValue = defaultValue == null ? "" : String(defaultValue);
            const controlLabel = port.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
            return (
              <div
                key={`in-${port}-${index}`}
                className={`node-port node-port-input ${isControl ? "control-port" : ""} ${isHighlighted ? "port-highlighted" : ""}`}
                onMouseEnter={() => data.onPortHover?.({ nodeId: id, port, direction: "input" })}
                onMouseLeave={() => data.onPortHover?.(null)}
              >
                <Handle
                  type="target"
                  position={Position.Left}
                  id={port}
                  className={`node-handle ${isControl ? "control-handle" : ""} ${isHighlighted ? "handle-highlighted" : ""}`}
                  style={handleStyle}
                >
                  {isControl && (
                    <svg className="control-handle-icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  )}
                </Handle>
                {!isControl && (
                  <div className="node-port-label-group">
                    <span className="node-port-name">{port}</span>
                    <span
                      className="port-type-text"
                      style={{ color }}
                      title={`Accepts ${formatPortTypeLabel(portType)}`}
                    >
                      {formatPortTypeLabel(portType)}
                    </span>
                  </div>
                )}
                {showControlLabel && (
                  <span className="control-port-label">{controlLabel}</span>
                )}
                {!isControl && (
                  <div className="node-port-input-control">
                    {portKind === "boolean" ? (
                      <input
                        type="checkbox"
                        className="node-input-checkbox nodrag"
                        checked={Boolean(resolvedValue)}
                        disabled={isConnected}
                        onChange={(event) =>
                          data.onInputValueChange?.(id, port, event.target.checked)
                        }
                      />
                    ) : (
                      <input
                        type={portKind === "int" || portKind === "float" || portKind === "number" ? "number" : "text"}
                        step={portKind === "int" ? 1 : "any"}
                        className="node-input-field nodrag"
                        value={`${resolvedValue ?? ""}`}
                        placeholder={placeholderValue}
                        disabled={isConnected}
                        onChange={(event) => {
                          const raw = event.target.value;
                          if (portKind === "int" || portKind === "float" || portKind === "number") {
                            const numeric = raw === ""
                              ? null
                              : portKind === "int"
                                ? parseInt(raw, 10)
                                : Number(raw);
                            data.onInputValueChange?.(id, port, Number.isNaN(numeric) ? null : numeric);
                            return;
                          }
                          data.onInputValueChange?.(id, port, raw);
                        }}
                      />
                    )}
                  </div>
                )}
              </div>
            );
          })}
          {data.nodeType === "core.container.make_array" && (
            <button
              type="button"
              className="node-port-add nodrag"
              onClick={(event) => {
                event.stopPropagation();
                data.onAddInputPort?.(id);
              }}
              title="Add array item input"
            >
              +
            </button>
          )}
        </div>
        <div className="node-port-column">
          {data.output_ports.map((port, index) => {
            const portType = resolvePortType(port, "output");
            const portKind = getTypeKind(portType);
            const isControl = portKind === "control";
            const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
            const color = getPortTypeColor(portType);
            const handleStyle: React.CSSProperties = { ["--handle-color" as string]: color };
            const isHighlighted = data.highlightedPort?.port === port && data.highlightedPort?.direction === "output";
            const controlLabel = port.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
            return (
              <div
                key={`out-${port}-${index}`}
                className={`node-port node-port-output ${isControl ? "control-port" : ""} ${isHighlighted ? "port-highlighted" : ""}`}
                onMouseEnter={() => data.onPortHover?.({ nodeId: id, port, direction: "output" })}
                onMouseLeave={() => data.onPortHover?.(null)}
              >
                {!isControl && (
                  <div className="node-port-label-group">
                    <span className="node-port-label">{port}</span>
                    <span
                      className="port-type-text"
                      style={{ color }}
                      title={`Emits ${formatPortTypeLabel(portType)}`}
                    >
                      {formatPortTypeLabel(portType)}
                    </span>
                  </div>
                )}
                {showControlLabel && (
                  <span className="control-port-label">{controlLabel}</span>
                )}
                <Handle
                  type="source"
                  position={Position.Right}
                  id={port}
                  className={`node-handle ${isControl ? "control-handle" : ""} ${isHighlighted ? "handle-highlighted" : ""}`}
                  style={handleStyle}
                >
                  {isControl && (
                    <svg className="control-handle-icon" viewBox="0 0 24 24" aria-hidden="true">
                      <path d="M8 5v14l11-7z" />
                    </svg>
                  )}
                </Handle>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};

export default BlueprintNode;
