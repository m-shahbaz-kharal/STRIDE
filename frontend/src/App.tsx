import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Handle,
  MiniMap,
  Node,
  NodeProps,
  OnSelectionChangeParams,
  Position,
  ReactFlowProvider,
  useEdgesState,
  useNodesState,
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

const formatValue = (value: unknown): string => {
  if (value === null || value === undefined) return "null";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
};

const OutputValue = ({ port, value }: { port: string; value: unknown }) => {
  const [expanded, setExpanded] = useState(false);
  const formatted = formatValue(value);
  const isLong = formatted.length > 12;
  const displayValue = isLong && !expanded ? formatted.slice(0, 10) + "…" : formatted;

  return (
    <span 
      className={`node-output-value ${isLong ? "expandable" : ""} ${expanded ? "expanded" : ""}`}
      onClick={(e) => {
        if (isLong) {
          e.stopPropagation();
          setExpanded(!expanded);
        }
      }}
      title={isLong ? formatted : undefined}
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

  return (
    <div
      className={`resize-zone nodrag ${corner}`}
      style={{
        position: "absolute",
        [isTop ? "top" : "bottom"]: "-2px",
        [isLeft ? "left" : "right"]: "-2px",
        width: "18px",
        height: "18px",
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
            top: "3px",
            left: "3px",
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

const BlueprintNode = ({ id, data }: NodeProps<BlueprintNodeData>) => {
  const [hoveredCorner, setHoveredCorner] = useState<Corner>(null);
  const [isResizing, setIsResizing] = useState(false);
  const [nodeSize, setNodeSize] = useState({ width: data.width || 0, height: data.height || 0 });
  const nodeRef = useRef<HTMLDivElement>(null);
  const startPosRef = useRef({ x: 0, y: 0, width: 0, height: 0 });
  const resizeCornerRef = useRef<Corner>(null);

  const executionStatusClass = getExecutionStatusClass(data.executionStatus);
  const statusClass = data.breakpoint
    ? "node-breakpoint"
    : executionStatusClass || (data.last_outputs ? "node-executed" : "");
  const highlightClass = data.isHighlighted ? "node-highlighted" : "";

  const handleResizeStart = useCallback((corner: Corner, e: React.MouseEvent) => {
    if (!corner || !nodeRef.current) return;
    
    e.stopPropagation();
    e.preventDefault();
    const width = nodeRef.current.offsetWidth;
    const height = nodeRef.current.offsetHeight;
    startPosRef.current = { x: e.clientX, y: e.clientY, width, height };
    resizeCornerRef.current = corner;
    setNodeSize({ width, height });
    setIsResizing(true);
  }, []);

  const titleLength = data.displayName.length + data.nodeType.length;
  const maxPorts = Math.max(data.input_ports.length, data.output_ports.length);
  const MIN_WIDTH = Math.max(200, 100 + titleLength * 7);
  const MIN_HEIGHT = Math.max(80, 42 + maxPorts * 22);

  useEffect(() => {
    if (!isResizing) return;

    const handleMouseMove = (e: MouseEvent) => {
      const corner = resizeCornerRef.current;
      if (!corner) return;
      
      const dx = e.clientX - startPosRef.current.x;
      const dy = e.clientY - startPosRef.current.y;
      
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

  const sizeStyle = nodeSize.width > 0 && nodeSize.height > 0 
    ? { width: nodeSize.width, height: nodeSize.height } 
    : {};
  
  const corners: Corner[] = ["bottom-right"];

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
        <div>
          <strong>{data.displayName}</strong>
          <span className="node-type-chip">{data.nodeType}</span>
        </div>
        <div className="node-header-right">
          {data.executionStatus === "running" && (
            <span className="node-status-chip running">
              <span className="status-dot pulse" />
              RUN
            </span>
          )}
          {data.executionStatus === "queued" && (
            <span className="node-status-chip queued">QUEUE</span>
          )}
          {data.executionDuration !== undefined && data.executionStatus === "completed" && (
            <span className="node-timing-chip" title={`Execution time: ${data.executionDuration.toFixed(1)}ms`}>
              {data.executionDuration < 1 ? "<1" : data.executionDuration.toFixed(0)}ms
            </span>
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

const StepIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
  </svg>
);

const SelectionIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M3 5h2V3c-1.1 0-2 .9-2 2zm0 8h2v-2H3v2zm4 8h2v-2H7v2zM3 9h2V7H3v2zm10-6h-2v2h2V3zm6 0v2h2c0-1.1-.9-2-2-2zM5 21v-2H3c0 1.1.9 2 2 2zm-2-4h2v-2H3v2zM9 3H7v2h2V3zm2 18h2v-2h-2v2zm8-8h2v-2h-2v2zm0 8c1.1 0 2-.9 2-2h-2v2zm0-12h2V7h-2v2zm0 8h2v-2h-2v2zm-4 4h2v-2h-2v2zm0-16h2V3h-2v2z" />
    <path d="M10 8l6 4-6 4V8z" />
  </svg>
);

const StreamIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M4 6h2v12H4zm14 0h2v12h-2zM9 6h2v12H9zm5-4h2v20h-2z" opacity="0.3" />
    <path d="M4 6h2v12H4zm14 0h2v12h-2zM9 6h2v12H9zm5-4h2v20h-2z" />
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
  const [useStreaming, setUseStreaming] = useState(true);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const nodeIdRef = useRef(1);

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
          },
        };
      })
    );
  }, [nodeStatuses, trace, isRunning, setNodes]);

  // Update edges for running state (animated flow)
  useEffect(() => {
    setEdges((existing) =>
      existing.map((edge) => ({
        ...edge,
        animated: isRunning,
        style: {
          ...edge.style,
          stroke: isRunning 
            ? nodeStatuses.get(edge.source) === "completed" 
              ? "var(--accent-green)" 
              : "var(--accent-blue)"
            : "#4a9eff",
          strokeWidth: isRunning ? 2.5 : 2,
        },
      }))
    );
  }, [isRunning, nodeStatuses, setEdges]);

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

  const handleToggleBreakpoint = useCallback(
    (nodeId: string) =>
      updateNodeData(nodeId, (data) => ({ ...data, breakpoint: !data.breakpoint })),
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

  const handleAddNode = useCallback(
    (nodeType: NodeTypeDefinition) => {
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }
      const id = `node-${nodeIdRef.current++}`;
      const position = { x: 120 + nodes.length * 36, y: 80 + nodes.length * 32 };
      
      const titleLength = nodeType.display_name.length + nodeType.node_type.length;
      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const initialWidth = Math.max(200, 100 + titleLength * 7);
      const initialHeight = Math.max(80, 42 + maxPorts * 22);
      
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
          width: initialWidth,
          height: initialHeight,
        },
      };
      setNodes((existing) => existing.concat(payload));
    },
    [handleDeleteNode, nodes.length, setNodes]
  );

  const graphStats = useMemo(
    () => ({
      nodes: nodes.length,
      edges: edges.length,
      breakpoints: nodes.filter((node) => node.data.breakpoint).length,
      selection: selectedNodeIds.length,
    }),
    [edges.length, nodes, selectedNodeIds.length]
  );

  const buildGraphPayload = useCallback(
    (mode: "full" | "selection", extras?: { max_steps?: number }) => {
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
      if (mode === "selection" && selectedNodeIds.length) {
        options.target_nodes = selectedNodeIds;
      }
      const breakpoints = nodes.filter((node) => node.data.breakpoint).map((node) => node.id);
      if (breakpoints.length) {
        options.breakpoints = breakpoints;
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
    [edges, nodes, selectedNodeIds]
  );

  const handleRunGraph = useCallback(
    async (mode: "full" | "selection", extras?: { max_steps?: number }) => {
      if (isRunning || nodes.length === 0) return;

      const payload = buildGraphPayload(mode, extras);

      // Clear previous execution states
      setNodes((existing) =>
        existing.map((node) => ({
          ...node,
          data: {
            ...node.data,
            executionStatus: undefined,
            executionDuration: undefined,
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
    [buildGraphPayload, isConnected, isRunning, nodes.length, runGraph, runGraphSync, setNodes, useStreaming]
  );

  const handleConnect = useCallback(
    (connection: Parameters<typeof addEdge>[0]) => {
      if (!connection.sourceHandle || !connection.targetHandle) return;
      setEdges((existing) =>
        addEdge(
          {
            ...connection,
            animated: false,
            style: { stroke: "#4a9eff", strokeWidth: 2 },
          },
          existing
        )
      );
    },
    [setEdges]
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
                if (node.data?.breakpoint) return "#ff5555";
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

        <header className="overlay-header">
          <div className="header-left">
            <h1>LiGuard Graph</h1>
            <div className="header-stats">
              <span className="stat-badge">{graphStats.nodes} nodes</span>
              <span className="stat-badge">{graphStats.edges} edges</span>
              {graphStats.breakpoints > 0 && (
                <span className="stat-badge breakpoint">{graphStats.breakpoints} BP</span>
              )}
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
              className={`icon-btn stream-toggle ${useStreaming ? "active" : ""}`}
              onClick={() => setUseStreaming(!useStreaming)}
              title={useStreaming ? "Streaming Mode (WebSocket)" : "Batch Mode (HTTP)"}
            >
              <StreamIcon />
            </button>
            <div className="toolbar-divider" />
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
              className="icon-btn"
              onClick={() => handleRunGraph("selection")}
              disabled={isRunning || graphStats.selection === 0}
              title={`Run Selection (${graphStats.selection})`}
            >
              <SelectionIcon />
            </button>
            <button
              className="icon-btn"
              onClick={() => handleRunGraph("full", { max_steps: 1 })}
              disabled={isRunning || nodes.length === 0}
              title="Step"
            >
              <StepIcon />
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
                  onToggleBreakpoint={handleToggleBreakpoint}
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
      </div>
    </ReactFlowProvider>
  );
};

export default App;
