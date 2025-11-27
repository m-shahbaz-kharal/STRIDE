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

import ExecutionControls from "./components/ExecutionControls";
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
            <div key={`in-${port}-${index}`} className="node-port">
              <Handle
                type="target"
                position={Position.Left}
                id={port}
                className="node-handle"
                style={{ top: 12 + index * 18 }}
              />
              <span>{port}</span>
            </div>
          ))}
        </div>
        <div className="node-port-column">
          {data.output_ports.map((port, index) => (
            <div key={`out-${port}-${index}`} className="node-port">
              <span>{port}</span>
              <Handle
                type="source"
                position={Position.Right}
                id={port}
                className="node-handle"
                style={{ top: 12 + index * 18 }}
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
            style: { stroke: "#0f62fe" },
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

  return (
    <ReactFlowProvider>
      <div className="app-shell">
        <header className="app-header">
          <div>
            <h1>LiGuard Graph Editor</h1>
            <p>
              Compose node graphs as you would in Unreal Blueprints or ComfyUI and execute them
              against the Python runtime.
            </p>
          </div>
          <div className="header-meta">
            <span>Nodes: {graphStats.nodes}</span>
            <span>Edges: {graphStats.edges}</span>
            <span>Breakpoints: {graphStats.breakpoints}</span>
          </div>
        </header>
        <div className="workspace">
          <aside className="panel-col palette-col">
            <NodePalette nodeTypes={nodeLibrary} onAddNode={handleAddNode} />
          </aside>

          <section className="canvas-col">
            <ExecutionControls
              isRunning={isRunning}
              selectionCount={graphStats.selection}
              breakpointCount={graphStats.breakpoints}
              onRunGraph={handleRunGraph}
              onRunSelection={handleRunSelection}
              onStep={handleStep}
              lastRunMode={lastRunMode}
            />
            <div className="graph-toolbar">
              <div className="graph-toolbar-meta">
                <span>Selection: {graphStats.selection}</span>
                <span>Breakpoints set: {graphStats.breakpoints}</span>
                <span>Last run: {lastRunMode || "n/a"}</span>
              </div>
              <div className="toolbar-actions">
                <button
                  type="button"
                  onClick={handleDeleteSelected}
                  disabled={graphStats.selection === 0}
                >
                  Delete Selected
                </button>
              </div>
            </div>
            <div className="reactflow-wrapper">
              <ReactFlow
                nodes={nodes}
                edges={edges}
                onNodesChange={onNodesChange}
                onEdgesChange={onEdgesChange}
                onConnect={handleConnect}
                onSelectionChange={handleSelectionChange}
                nodeTypes={nodeTypes}
                fitView
                connectionLineStyle={{ stroke: "#0f62fe" }}
                attributionPosition="bottom-left"
              >
                <Background gap={16} />
                <Controls showZoom={false} />
                <MiniMap nodeColor={(node) => (node.data?.breakpoint ? "#ff7a7a" : "#1f6feb")} />
              </ReactFlow>
            </div>
            <div className="trace-hints">
              <div>
                <strong>Device planner</strong>
                <p>Units: {units.length}</p>
              </div>
              <div>
                <strong>Last error</strong>
                <p>{lastError ?? "None"}</p>
              </div>
            </div>
          </section>

          <aside className="panel-col inspector-col">
            <NodeInspector
              node={selectedNode}
              onDeviceHintChange={handleDeviceHintChange}
              onParamChange={handleParamChange}
              onToggleBreakpoint={handleToggleBreakpoint}
            />
            <LogPanel trace={trace} units={units} outputs={outputs} error={lastError} />
          </aside>
        </div>
      </div>
    </ReactFlowProvider>
  );
};

export default App;

