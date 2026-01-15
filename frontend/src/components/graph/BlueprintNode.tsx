import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Handle, NodeProps, Position, useReactFlow, useStore, useUpdateNodeInternals, Edge } from "reactflow";

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

// PERF: Equality function for edge arrays - prevents re-renders when edges haven't changed
const edgeArrayEquals = (a: Edge[], b: Edge[]): boolean => {
  if (a.length !== b.length) return false;
  for (let i = 0; i < a.length; i++) {
    if (a[i].id !== b[i].id) return false;
    // Check if target handle changed (affects connection status)
    if (a[i].targetHandle !== b[i].targetHandle) return false;
    if (a[i].sourceHandle !== b[i].sourceHandle) return false;
  }
  return true;
};

// PERF: Equality function for connected source nodes Map
const sourceMapEquals = (a: Map<string, any>, b: Map<string, any>): boolean => {
  if (a.size !== b.size) return false;
  for (const [key, nodeA] of a) {
    const nodeB = b.get(key);
    if (!nodeB) return false;
    // Only care about last_outputs which affects displayed values
    if (nodeA?.data?.last_outputs !== nodeB?.data?.last_outputs) return false;
  }
  return true;
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

  // PERF: Only subscribe to edges that connect to THIS node, not all edges
  // Uses equality function to prevent re-renders when edge array is semantically identical
  const relevantEdges = useStore(
    useCallback((state) => {
      const allEdges = state.edges || [];
      return allEdges.filter((edge) => edge.source === id || edge.target === id);
    }, [id]),
    edgeArrayEquals
  );

  // PERF: Only get source nodes for our incoming edges, not entire nodeInternals
  // Uses equality function to prevent re-renders when source outputs haven't changed
  const connectedSources = useStore(
    useCallback((state) => {
      const allEdges = state.edges || [];
      const nodeInt = state.nodeInternals;
      if (!nodeInt) return new Map();

      const sourceIds = new Set<string>();
      for (const edge of allEdges) {
        if (edge.target === id) sourceIds.add(edge.source);
      }

      const result = new Map();
      for (const sourceId of sourceIds) {
        const node = nodeInt.get(sourceId);
        if (node) result.set(sourceId, node);
      }
      return result;
    }, [id]),
    sourceMapEquals
  );

  const { showLogsPopup } = usePopups();
  const updateNodeInternals = useUpdateNodeInternals();

  // Notify React Flow when handles change (ports added/removed/toggled)
  useEffect(() => {
    updateNodeInternals(id);
  }, [id, data.input_ports, data.output_ports, data.showControlPorts, data.hoverControlPorts, data.executionMode, updateNodeInternals]);

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

  const inputPortTypes = data.input_port_types || data.metadata?.input_port_types || {};
  const outputPortTypes = data.output_port_types || data.metadata?.output_port_types || {};
  const isCoreControlNode = data.nodeType.startsWith("core.control");
  const extraInputRows = data.nodeType === "core.container.make_array" ? 1 : 0;
  const maxPorts = Math.max(data.input_ports.length + extraInputRows, data.output_ports.length);
  const MIN_HEIGHT = computeNodeDimensions(maxPorts, { paramCount: 0 }).height;
  const inputSpecMap = useMemo(() => {
    const specs = data.metadata?.inputs ?? [];
    return new Map(specs.map((spec) => [spec.name, spec]));
  }, [data.metadata?.inputs]);

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
      relevantEdges.some((edge) => edge.target === id && edge.targetHandle === port),
    [relevantEdges, id]
  );

  const isOutputConnected = useCallback(
    (port: string) =>
      relevantEdges.some((edge) => edge.source === id && edge.sourceHandle === port),
    [relevantEdges, id]
  );

  const hasControlPorts = useMemo(() => {
    const inputHasControl = data.input_ports.some((port) => getTypeKind(resolvePortType(port, "input")) === "control");
    const outputHasControl = data.output_ports.some((port) => getTypeKind(resolvePortType(port, "output")) === "control");
    return inputHasControl || outputHasControl;
  }, [data.input_ports, data.output_ports, getTypeKind, resolvePortType]);

  // Control ports are hidden by default in dataflow mode unless connected
  const isControlPortVisible = useCallback(
    (port: string, direction: "input" | "output", portKind: string) => {
      // Always show non-control ports
      if (portKind !== "control") return true;

      // In controlflow mode or when showControlPorts is true, always show
      if (data.executionMode === "controlflow" || data.showControlPorts || data.hoverControlPorts || isCoreControlNode) return true;

      // In dataflow mode, only show if connected
      if (direction === "input") {
        return isInputConnected(port);
      }
      return isOutputConnected(port);
    },
    [data.executionMode, data.showControlPorts, data.hoverControlPorts, isCoreControlNode, isInputConnected, isOutputConnected]
  );

  const getConnectedOutput = useCallback(
    (port: string) => {
      const edge = relevantEdges.find((item) => item.target === id && item.targetHandle === port);
      if (!edge || !edge.sourceHandle) {
        return { hasValue: false, value: undefined };
      }
      const sourceNode = connectedSources?.get(edge.source);
      const outputs = sourceNode?.data?.last_outputs;
      if (outputs && Object.prototype.hasOwnProperty.call(outputs, edge.sourceHandle)) {
        return { hasValue: true, value: outputs[edge.sourceHandle] };
      }
      return { hasValue: false, value: undefined };
    },
    [relevantEdges, id, connectedSources]
  );

  const getInputDefault = useCallback(
    (port: string) => data.metadata?.inputs?.find((input) => input.name === port)?.default,
    [data.metadata?.inputs]
  );

  const desiredDimensions = useMemo(() => {
    const estimateTextWidth = (value: string) => value.length * 7;
    const inputLabels = data.input_ports ?? [];
    const outputLabels = data.output_ports ?? [];

    const maxInput = Math.max(0, ...inputLabels.map((label) => estimateTextWidth(label)));
    const maxOutput = Math.max(0, ...outputLabels.map((label) => estimateTextWidth(label)));
    const headerWidth = estimateTextWidth(data.displayName ?? "") + 120;
    const portRowWidth = maxInput + maxOutput + 84 + 120;
    const width = Math.max(MIN_NODE_WIDTH, headerWidth, portRowWidth);
    const { height } = computeNodeDimensions(maxPorts, { paramCount: 0, minWidth: width });
    return { width, height };
  }, [data.displayName, data.input_ports, data.output_ports, maxPorts]);

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

  useEffect(() => {
    if (isResizing) return;
    if (nodeSize.width >= desiredDimensions.width && nodeSize.height >= desiredDimensions.height) {
      return;
    }
    setNodeSize((prev) => ({
      width: Math.max(prev.width, desiredDimensions.width),
      height: Math.max(prev.height, desiredDimensions.height),
    }));
  }, [desiredDimensions.height, desiredDimensions.width, isResizing, nodeSize.height, nodeSize.width]);

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
          {!isCoreControlNode && (
            <button
              className={`node-action-btn cache-toggle-btn nodrag${data.cacheEnabled ? " cache-toggle-on" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                data.onToggleCache?.(id);
              }}
              title={data.cacheEnabled ? "Disable node caching" : "Enable node caching"}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2c-4.42 0-8 1.79-8 4s3.58 4 8 4 8-1.79 8-4-3.58-4-8-4zm0 10c-4.42 0-8-1.79-8-4v4c0 2.21 3.58 4 8 4s8-1.79 8-4V8c0 2.21-3.58 4-8 4zm0 6c-4.42 0-8-1.79-8-4v4c0 2.21 3.58 4 8 4s8-1.79 8-4v-4c0 2.21-3.58 4-8 4z" />
              </svg>
            </button>
          )}
          {/* Toggle control ports visibility button */}
          {hasControlPorts && !isCoreControlNode && (
            <button
              className={`node-action-btn control-toggle-btn nodrag${data.showControlPorts ? " control-toggle-on" : ""}`}
              onClick={(e) => {
                e.stopPropagation();
                data.onToggleControlPorts?.(id);
              }}
              title={data.showControlPorts ? "Hide control flow connectors" : "Show control flow connectors"}
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                {/* Branch/flow icon */}
                <path d="M14 4l2.29 2.29-2.88 2.88 1.42 1.42 2.88-2.88L20 10V4h-6zm-4 0H4v6l2.29-2.29 4.71 4.7V20h2v-8.41l-5.29-5.3L10 4z" />
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
          {data.input_ports.map((port, index) => {
            const portType = resolvePortType(port, "input");
            const portKind = getTypeKind(portType);
            const isControl = portKind === "control";

            // Hide control ports when toggle is off and not connected
            if (!isControlPortVisible(port, "input", portKind)) {
              return null;
            }

            const color = getPortTypeColor(portType);
            const handleStyle: React.CSSProperties = { ["--handle-color" as string]: color };

            const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
            const isHighlighted = data.highlightedPort?.port === port && data.highlightedPort?.direction === "input";
            const isConnected = isInputConnected(port);
            const inputValue = data.inputValues?.[port];
            const defaultValue = getInputDefault(port);
            const hasInputValue = Object.prototype.hasOwnProperty.call(data.inputValues ?? {}, port);
            const resolvedValue = hasInputValue ? inputValue : defaultValue;
            const connectedInfo = isConnected ? getConnectedOutput(port) : null;
            const hasCachedValue = Boolean(connectedInfo?.hasValue);
            const displayValue = isConnected ? (hasCachedValue ? connectedInfo?.value : "") : resolvedValue;
            const isEmptyConnected = isConnected && !hasCachedValue;
            const placeholderValue = isEmptyConnected ? "" : (defaultValue == null ? "" : String(defaultValue));
            const inputSpec = inputSpecMap.get(port);
            const inputUi = inputSpec?.ui as { control?: string; options?: string[] } | undefined;
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
                      <path d="M8 6.82v10.36c0 .79.87 1.27 1.54.84l8.14-5.18c.62-.39.62-1.29 0-1.69L9.54 5.98C8.87 5.55 8 6.03 8 6.82z" />
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
                    {(() => {
                      const isSelect = inputUi?.control === "select";
                      const options = inputUi?.options || (typeof portType === "object" ? portType.metadata?.options : undefined);

                      if (isSelect && options && Array.isArray(options)) {
                        return (
                          <select
                            className={`node-input-field nodrag${isEmptyConnected ? " empty" : ""}`}
                            value={`${displayValue ?? ""}`}
                            disabled={isConnected}
                            onChange={(event) => data.onInputValueChange?.(id, port, event.target.value)}
                          >
                            {isEmptyConnected && (
                              <option value="">No cached value</option>
                            )}
                            {(options as any[]).map((option: any) => {
                              const value = typeof option === "object" && option !== null ? option.value : option;
                              const label = typeof option === "object" && option !== null ? (option.label || option.value) : option;
                              return (
                                <option key={String(value)} value={String(value)}>
                                  {label}
                                </option>
                              );
                            })}
                          </select>
                        );
                      }

                      if (portKind === "boolean") {
                        return (
                          <input
                            type="checkbox"
                            className={`node-input-checkbox nodrag${isEmptyConnected ? " empty" : ""}`}
                            checked={isConnected ? (hasCachedValue ? Boolean(displayValue) : false) : Boolean(displayValue)}
                            disabled={isConnected}
                            onChange={(event) =>
                              data.onInputValueChange?.(id, port, event.target.checked)
                            }
                          />
                        );
                      }

                      return (
                        <input
                          type={portKind === "int" || portKind === "float" || portKind === "number" ? "number" : "text"}
                          step={portKind === "int" ? 1 : "any"}
                          className={`node-input-field nodrag${isEmptyConnected ? " empty" : ""}`}
                          value={`${displayValue ?? ""}`}
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
                      );
                    })()}
                    {isEmptyConnected && (
                      <span className="node-input-empty-label">no cache</span>
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

            // Hide control ports when toggle is off and not connected
            if (!isControlPortVisible(port, "output", portKind)) {
              return null;
            }

            const color = getPortTypeColor(portType);
            const handleStyle: React.CSSProperties = { ["--handle-color" as string]: color };

            const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
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
                      <path d="M8 6.82v10.36c0 .79.87 1.27 1.54.84l8.14-5.18c.62-.39.62-1.29 0-1.69L9.54 5.98C8.87 5.55 8 6.03 8 6.82z" />
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

// Memoize to prevent re-renders when other nodes change
// Only re-render when this node's data, edges, or selection state changes
export default React.memo(BlueprintNode, (prevProps, nextProps) => {
  // Check if node data changed
  if (prevProps.data !== nextProps.data) return false;
  if (prevProps.id !== nextProps.id) return false;
  if (prevProps.selected !== nextProps.selected) return false;
  if (prevProps.dragging !== nextProps.dragging) return false;

  // Deep equality for critical data fields
  if (prevProps.data.executionStatus !== nextProps.data.executionStatus) return false;
  if (prevProps.data.isHighlighted !== nextProps.data.isHighlighted) return false;
  if (prevProps.data.last_outputs !== nextProps.data.last_outputs) return false;
  if (prevProps.data.highlightedPort !== nextProps.data.highlightedPort) return false;
  if (prevProps.data.cacheEnabled !== nextProps.data.cacheEnabled) return false;

  // Check for structural changes that affect handles
  if (prevProps.data.showControlPorts !== nextProps.data.showControlPorts) return false;
  if (prevProps.data.executionMode !== nextProps.data.executionMode) return false;
  if (prevProps.data.input_ports !== nextProps.data.input_ports) return false;
  if (prevProps.data.output_ports !== nextProps.data.output_ports) return false;

  return true;
});
