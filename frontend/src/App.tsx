import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Edge,
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
import {
  BlueprintNodeData,
  ExecutionTraceEntry,
  ExecutionUnit,
  NodeTypeDefinition,
} from "./types";

const BlueprintNode = ({ data }: NodeProps<BlueprintNodeData>) => {
  const executed = Boolean(data.last_device);
  const statusClass = data.breakpoint
    ? "node-breakpoint"
    : executed
    ? "node-executed"
    : "";

  return (
    <div className={`blueprint-node ${statusClass}`}>
      <div className="node-header">
        <div>
          <strong>{data.displayName}</strong>
          <span className="node-type-chip">{data.nodeType}</span>
        </div>
        <span className="node-device-chip">{data.device_hint.toUpperCase()}</span>
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
          {data.output_ports.map((port, index) => (
            <div key={`out-${port}-${index}`} className="node-port node-port-output">
              <span>{port}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                className="node-handle"
              />
            </div>
          ))}
        </div>
      </div>

      <div className="node-footer">
        {data.last_device && <span>Last run on {data.last_device.toUpperCase()}</span>}
        {data.last_outputs && (
          <span className="node-preview">
            {Object.entries(data.last_outputs)
              .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
              .join(", ")}
          </span>
        )}
      </div>
    </div>
  );
};

// Play Icon SVG
const PlayIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M8 5v14l11-7z" />
  </svg>
);

// Step Icon SVG
const StepIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" />
  </svg>
);

// Selection Run Icon SVG
const SelectionIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M3 5h2V3c-1.1 0-2 .9-2 2zm0 8h2v-2H3v2zm4 8h2v-2H7v2zM3 9h2V7H3v2zm10-6h-2v2h2V3zm6 0v2h2c0-1.1-.9-2-2-2zM5 21v-2H3c0 1.1.9 2 2 2zm-2-4h2v-2H3v2zM9 3H7v2h2V3zm2 18h2v-2h-2v2zm8-8h2v-2h-2v2zm0 8c1.1 0 2-.9 2-2h-2v2zm0-12h2V7h-2v2zm0 8h2v-2h-2v2zm-4 4h2v-2h-2v2zm0-16h2V3h-2v2z" />
    <path d="M10 8l6 4-6 4V8z" />
  </svg>
);

// Delete Icon SVG
const DeleteIcon = () => (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor">
    <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
  </svg>
);

// Chevron Icons
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

const App = () => {
  const [nodeLibrary, setNodeLibrary] = useState<NodeTypeDefinition[]>([]);
  const [trace, setTrace] = useState<ExecutionTraceEntry[]>([]);
  const [outputs, setOutputs] = useState<Record<string, unknown>>({});
  const [units, setUnits] = useState<ExecutionUnit[]>([]);
  const [isRunning, setIsRunning] = useState(false);
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const [lastRunMode, setLastRunMode] = useState<string>("");
  const nodeIdRef = useRef(1);

  // Panel collapse states
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
  
  // Panel width states (for resizing)
  const [leftPanelWidth, setLeftPanelWidth] = useState(260);
  const [rightPanelWidth, setRightPanelWidth] = useState(300);
  
  // Resizing states
  const [isResizingLeft, setIsResizingLeft] = useState(false);
  const [isResizingRight, setIsResizingRight] = useState(false);

  const [nodes, setNodes, onNodesChange] = useNodesState<Node<BlueprintNodeData>>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge[]>([]);

  const nodeTypes = useMemo(() => ({ blueprint: BlueprintNode }), []);

  useEffect(() => {
    fetch("/api/node-types")
      .then(async (response) => {
        if (!response.ok) {
          throw new Error("Unable to load node registry.");
        }
        const data: NodeTypeDefinition[] = await response.json();
        setNodeLibrary(data);
      })
      .catch(() => {
        setNodeLibrary([]);
      });
  }, []);

  // Handle mouse move for resizing
  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isResizingLeft) {
        const newWidth = Math.min(Math.max(180, e.clientX), 400);
        setLeftPanelWidth(newWidth);
      }
      if (isResizingRight) {
        const newWidth = Math.min(Math.max(200, window.innerWidth - e.clientX), 500);
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

  const handleDeviceHintChange = useCallback(
    (nodeId: string, hint: string) =>
      updateNodeData(nodeId, (data) => ({ ...data, device_hint: hint })),
    [updateNodeData]
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

  const handleAddNode = useCallback(
    (nodeType: NodeTypeDefinition) => {
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }
      const id = `node-${nodeIdRef.current++}`;
      const position = { x: 120 + nodes.length * 36, y: 80 + nodes.length * 32 };
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
          device_hint: "auto",
          breakpoint: false,
          metadata: nodeType,
        },
      };
      setNodes((existing) => existing.concat(payload));
    },
    [nodes.length, setNodes]
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
        device_hint: node.data.device_hint,
      }));

      const linkPayload = edges
        .filter((edge) => edge.sourceHandle && edge.targetHandle)
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

  const runGraph = useCallback(
    async (mode: "full" | "selection", extras?: { max_steps?: number }) => {
      if (isRunning || nodes.length === 0) {
        return;
      }
      setIsRunning(true);
      setLastError(null);
      const modeLabel = extras?.max_steps
        ? `${mode} (step ${extras.max_steps})`
        : mode === "selection"
        ? "selection"
        : "full";
      setLastRunMode(modeLabel);

      const payload = buildGraphPayload(mode, extras);
      try {
        const response = await fetch("/api/run-graph", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) {
          const message = await response.text();
          throw new Error(message || "Graph execution failed");
        }
        const data = await response.json();
        const traceResult: ExecutionTraceEntry[] = data.trace ?? [];
        setOutputs(data.outputs ?? {});
        setTrace(traceResult);
        setUnits(data.units ?? []);
        setNodes((existing) =>
          existing.map((node) => {
            const entry = traceResult.find((item) => item.node_id === node.id);
            if (!entry) {
              if (!node.data.last_outputs && !node.data.last_device) {
                return node;
              }
              return {
                ...node,
                data: { ...node.data, last_outputs: undefined, last_device: undefined },
              };
            }
            return {
              ...node,
              data: {
                ...node.data,
                last_device: entry.device,
                last_outputs: entry.outputs,
              },
            };
          })
        );
      } catch (error) {
        const message = error instanceof Error ? error.message : "Unknown execution error";
        setLastError(message);
      } finally {
        setIsRunning(false);
      }
    },
    [buildGraphPayload, isRunning, nodes.length, setNodes]
  );

  const handleRunGraph = useCallback(() => runGraph("full"), [runGraph]);
  const handleRunSelection = useCallback(() => runGraph("selection"), [runGraph]);
  const handleStep = useCallback(() => runGraph("full", { max_steps: 1 }), [runGraph]);

  const handleConnect = useCallback(
    (connection: Parameters<typeof addEdge>[0]) => {
      if (!connection.sourceHandle || !connection.targetHandle) {
        return;
      }
      setEdges((existing) =>
        addEdge(
          {
            ...connection,
            animated: true,
            style: { stroke: "#4a9eff" },
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

  const handleDeleteSelected = useCallback(() => {
    if (selectedNodeIds.length === 0) {
      return;
    }
    const removalSet = new Set(selectedNodeIds);
    setNodes((current) => current.filter((node) => !removalSet.has(node.id)));
    setEdges((current) =>
      current.filter(
        (edge) => !removalSet.has(edge.source) && !removalSet.has(edge.target)
      )
    );
    setSelectedNodeIds([]);
    setSelectedNodeId(null);
  }, [selectedNodeIds, setEdges, setNodes]);

  // Calculate actual panel widths for dynamic positioning
  const actualLeftWidth = leftPanelCollapsed ? 0 : leftPanelWidth;
  const actualRightWidth = rightPanelCollapsed ? 0 : rightPanelWidth;
  const collapseBtnWidth = 24; // Width of collapse button area

  return (
    <ReactFlowProvider>
      <div className="app-shell">
        {/* Full-page ReactFlow Canvas */}
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
              style={{ left: actualLeftWidth}}
            />
            <MiniMap 
              nodeColor={(node) => (node.data?.breakpoint ? "#ff5555" : "#4a9eff")} 
              maskColor="rgba(0,0,0,0.8)"
              style={{ 
                backgroundColor: "rgba(20,25,35,0.9)",
                right: actualRightWidth
              }}
            />
          </ReactFlow>
        </div>

        {/* Overlay Header - fixed full width */}
        <header className="overlay-header">
          <div className="header-left">
            <h1>Graph</h1>
            <div className="header-stats">
              <span className="stat-badge">{graphStats.nodes} nodes</span>
              <span className="stat-badge">{graphStats.edges} edges</span>
              {graphStats.breakpoints > 0 && (
                <span className="stat-badge breakpoint">{graphStats.breakpoints} BP</span>
              )}
            </div>
          </div>
          <div className="header-controls">
            <button
              className="icon-btn"
              onClick={handleRunGraph}
              disabled={isRunning || nodes.length === 0}
              title="Run Graph"
            >
              <PlayIcon />
              {isRunning && <span className="btn-spinner" />}
            </button>
            <button
              className="icon-btn"
              onClick={handleRunSelection}
              disabled={isRunning || graphStats.selection === 0}
              title={`Run Selection (${graphStats.selection})`}
            >
              <SelectionIcon />
            </button>
            <button
              className="icon-btn"
              onClick={handleStep}
              disabled={isRunning || nodes.length === 0}
              title="Step"
            >
              <StepIcon />
            </button>
            <div className="toolbar-divider" />
            <button
              className="icon-btn danger"
              onClick={handleDeleteSelected}
              disabled={graphStats.selection === 0}
              title="Delete Selected"
            >
              <DeleteIcon />
            </button>
            {lastError && <span className="error-indicator" title={lastError}>!</span>}
          </div>
        </header>

        {/* Left Panel - Node Library */}
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
        
        {/* Left Panel Collapse Button - always visible */}
        <button
          className="panel-collapse-btn left"
          style={{ left: leftPanelCollapsed ? 0 : leftPanelWidth }}
          onClick={() => setLeftPanelCollapsed(!leftPanelCollapsed)}
          title={leftPanelCollapsed ? "Expand Nodes" : "Collapse Nodes"}
        >
          {leftPanelCollapsed ? <ChevronRight /> : <ChevronLeft />}
        </button>

        {/* Right Panel - Logs & Inspector */}
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
                  onDeviceHintChange={handleDeviceHintChange}
                  onParamChange={handleParamChange}
                  onToggleBreakpoint={handleToggleBreakpoint}
                />
                <LogPanel trace={trace} units={units} outputs={outputs} error={lastError} />
              </div>
            </>
          )}
        </aside>
        
        {/* Right Panel Collapse Button - always visible */}
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
