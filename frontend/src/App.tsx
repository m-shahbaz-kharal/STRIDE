import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Connection,
  MiniMap,
  Node,
  Edge,
  OnSelectionChangeParams,
  ReactFlowProvider,
  SelectionMode,
  ReactFlowInstance,
  useEdgesState,
  useNodesState,
} from "reactflow";
import "reactflow/dist/style.css";

import BlueprintNode from "./components/graph/BlueprintNode";
import CustomEdge from "./components/graph/CustomEdge";
import TypeAwareConnectionLine from "./components/graph/TypeAwareConnectionLine";
import LogPanel from "./components/LogPanel";
import NodeInspector from "./components/NodeInspector";
import NodePalette from "./components/NodePalette";
import OutputsView from "./components/OutputsView";
import SmartConnectModal from "./components/SmartConnectModal";
import AppHeader from "./components/layout/AppHeader";
import ConnectionToast from "./components/ConnectionToast";
import SmartConnectLine from "./components/SmartConnectLine";
import { ChevronLeft, ChevronRight, CopyIcon, DeleteIcon } from "./components/Icons";
import { PopupProvider } from "./context/PopupContext";
import { useGraphExecution } from "./hooks/useGraphExecution";
import { useUndoRedo } from "./hooks/useUndoRedo";
import { useNodeLibrary } from "./hooks/useNodeLibrary";
import { usePanelResize } from "./hooks/usePanelResize";
import { useConnectionValidation } from "./hooks/useConnectionValidation";
import { useConnectionToast } from "./hooks/useConnectionToast";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { useNodeOperations } from "./hooks/useNodeOperations";
import { useSmartConnect } from "./hooks/useSmartConnect";
import {
  BlueprintNodeData,
  NodeTypeDefinition,
} from "./types";
import {
  MIN_NODE_WIDTH,
  bezierIntersectsRect,
  computeNodeDimensions,
  getPortTypeColor,
  HEADER_HEIGHT,
  PORT_ROW_HEIGHT,
} from "./graph/utils";

type RightPanelTab = "inspector" | "execution";

const App = () => {
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<string[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [useStreaming] = useState(true);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [hoveredPort, setHoveredPort] = useState<{ nodeId: string; port: string; direction: "input" | "output" } | null>(null);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());

  const [reactFlowInstance, setReactFlowInstance] = useState<ReactFlowInstance | null>(null);

  // Smart Connect state
  const [connectStartParams, setConnectStartParams] = useState<{
    nodeId: string | null;
    handleId: string | null;
    handleType: "source" | "target" | null;
  } | null>(null);

  const [connectionLineColor, setConnectionLineColor] = useState<string | undefined>(undefined);
  const [connectionLineIsInvalid, setConnectionLineIsInvalid] = useState(false);
  const [connectionLineDash, setConnectionLineDash] = useState<string | undefined>(undefined);
  const connectSucceededRef = useRef(false);

  // Right panel tab state
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>("inspector");

  // Header tab state
  const [headerTab, setHeaderTab] = useState<"graph-editor" | "outputs">("graph-editor");

  // Clipboard state for copy/paste (nodes only, no edges)
  const [clipboard, setClipboard] = useState<Node<BlueprintNodeData>[] | null>(null);

  // Custom selection box tracking for edge intersection selection
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionBox, setSelectionBox] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [previewEdgeIds, setPreviewEdgeIds] = useState<string[]>([]);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);

  const [nodes, setNodes, onNodesChange] = useNodesState<BlueprintNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // ========== Use extracted hooks ==========

  // Node library hook
  const { nodeLibrary } = useNodeLibrary();

  // Panel resize hook
  const {
    leftPanelCollapsed,
    rightPanelCollapsed,
    leftPanelWidth,
    rightPanelWidth,
    actualLeftWidth,
    actualRightWidth,
    toggleLeftPanel,
    toggleRightPanel,
    startResizingLeft,
    startResizingRight,
  } = usePanelResize();

  // Undo/Redo hook
  const { undo, redo, takeSnapshot } = useUndoRedo({
    nodes,
    edges,
    setNodes,
    setEdges,
  });

  // Node operations hook
  const {
    createNodeFromType,
    updateNodeData,
    handleParamChange,
    handleInputValueChange,
    handleAddInputPort,
    handleDeleteNode,
    clearNodeCache,
    clearAllCache,
    getPortYOffset,
  } = useNodeOperations({
    setNodes,
    setEdges,
    takeSnapshot,
  });

  // Connection validation hook
  const {
    nodeMap,
    arePortTypesCompatible,
    getPortTypeForHandle,
    getHandleRole,
    normalizeConnection,
    validateConnection,
  } = useConnectionValidation({
    nodes,
    connectStartParams,
  });

  // Smart connect hook
  const {
    smartConnectMenu,
    setSmartConnectMenu,
    openSmartConnect,
    closeSmartConnect,
    findCompatiblePortForSmartConnect,
    getCompatibleNodeTypes,
  } = useSmartConnect({
    getPortTypeForHandle,
    arePortTypesCompatible,
  });

  // Connection toast hook
  const { message: connectionMessage, showMessage: showConnectionMessage } = useConnectionToast();

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

  // Create handlers object for node data - keep stable to avoid re-renders
  // Note: onClearCache uses nodeMap which is already memoized
  const nodeHandlers = useMemo(() => ({
    onDelete: handleDeleteNode,
    onRunSelection: (nodeId: string) => handleRunGraph("selection", [nodeId]),
    onClearCache: async (nodeId: string) => {
      // Access node from nodeMap which stays current
      const node = nodeMap.get(nodeId);
      if (node) {
        try {
          await fetch(`/api/cache/clear/${encodeURIComponent(node.data.nodeType)}`, { method: "POST" });
        } catch (e) {
          console.error("Failed to clear backend cache for node type:", e);
        }
      }
      clearNodeCache(nodeId);
    },
    onInterrupt: async (nodeId: string) => {
      if (!executionId) return;
      try {
        await fetch(`/api/executions/${executionId}/cancel/${nodeId}`, { method: "POST" });
      } catch (e) {
        console.error("Failed to interrupt node:", e);
      }
    },
    onParamChange: handleParamChange,
    onPortHover: setHoveredPort,
    onInputValueChange: handleInputValueChange,
    onAddInputPort: handleAddInputPort,
    onToggleControlPorts: (nodeId: string) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, showControlPorts: !n.data.showControlPorts } }
            : n
        )
      );
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [handleDeleteNode, handleParamChange, handleInputValueChange, handleAddInputPort, clearNodeCache, executionId, nodeMap, setNodes]);

  // ========== Computed values ==========

  const outputsSummary = useMemo(() => {
    let images = 0;
    const streamIds = new Set<string>();
    let values = 0;

    for (const node of nodes) {
      const nodeOutputs = node.data.last_outputs;
      const display = nodeOutputs?.display;
      if (typeof display === "string" && display.startsWith("data:image")) {
        images += 1;
      }
      const image = nodeOutputs?.image;
      if (typeof image === "string" && image.startsWith("data:image")) {
        images += 1;
      }
      const streamId = nodeOutputs?.stream_id;
      if (typeof streamId === "string") {
        streamIds.add(streamId);
      }
    }

    for (const [key, value] of Object.entries(outputs)) {
      if (typeof value === "string" && value.startsWith("data:image")) {
        images += 1;
      } else if (typeof value === "string" && key.toLowerCase().includes("stream_id")) {
        streamIds.add(value);
      } else {
        values += 1;
      }
    }

    return { images, streams: streamIds.size, values };
  }, [nodes, outputs]);

  const graphSummary = useMemo(() => ({
    nodeCount: nodes.length,
    edgeCount: edges.length,
    selectedCount: selectedNodeIds.length + selectedEdgeIds.length,
  }), [nodes.length, edges.length, selectedNodeIds.length, selectedEdgeIds.length]);

  const selectedNodes = useMemo(
    () => nodes.filter((node) => selectedNodeIds.includes(node.id)),
    [nodes, selectedNodeIds]
  );

  const smartConnectNodeTypes = useMemo(
    () => getCompatibleNodeTypes(nodeLibrary),
    [getCompatibleNodeTypes, nodeLibrary]
  );

  // ========== Effects ==========

  // Update node execution states when nodeStatuses change
  useEffect(() => {
    if (nodeStatuses.size === 0 && !isRunning) return;

    const latestTraceByNode = new Map<string, typeof trace[number]>();
    for (const entry of trace) {
      latestTraceByNode.set(entry.node_id, entry);
    }

    setNodes((existing) =>
      existing.map((node) => {
        const status = nodeStatuses.get(node.id);
        const traceEntry = latestTraceByNode.get(node.id);

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

      for (const edge of edges) {
        if (edge.target === nodeId && !dependentIds.has(edge.source)) {
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

  // Update edges for running state
  useEffect(() => {
    setEdges((existing) =>
      existing.map((edge) => {
        const sourceNode = nodes.find((n) => n.id === edge.source);
        const sourceHasCachedOutput = Boolean(sourceNode?.data.last_outputs);
        const targetInRunningSet = runningNodeIds.has(edge.target);
        const shouldAnimate = isRunning && targetInRunningSet && !sourceHasCachedOutput;

        const sourceType = sourceNode?.data.nodeType ?? "";
        const isLoopNode = sourceType === "core.control.for" || sourceType === "core.control.repeat" || sourceType === "core.control.while";
        const isLoopBodyEdge = isLoopNode && edge.sourceHandle === "loop_body";
        const isLoopRunning = isLoopNode && nodeStatuses.get(edge.source) === "running";

        let strokeColor = "#4a9eff";
        if (isRunning && targetInRunningSet) {
          if (sourceHasCachedOutput) {
            strokeColor = "var(--accent-green)";
          } else if (nodeStatuses.get(edge.source) === "completed") {
            strokeColor = "var(--accent-green)";
          } else {
            strokeColor = "var(--accent-blue)";
          }
        }

        const loopDash = isLoopBodyEdge ? (isLoopRunning ? "2 4" : undefined) : edge.style?.strokeDasharray;

        return {
          ...edge,
          animated: shouldAnimate,
          style: {
            ...edge.style,
            stroke: strokeColor,
            strokeWidth: (isRunning && targetInRunningSet) ? 2.5 : 2,
            strokeDasharray: loopDash,
          },
        };
      })
    );
  }, [isRunning, nodeStatuses, runningNodeIds, nodes, setEdges]);

  // Clear running node set when execution completes
  useEffect(() => {
    if (!isRunning) {
      setRunningNodeIds(new Set());
    }
  }, [isRunning]);

  // Trim running set as nodes finish
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

  // Update nodes with highlighted state - only update nodes that changed
  useEffect(() => {
    const highlightSet = new Set(highlightedNodeIds);
    setNodes((existing) =>
      existing.map((node) => {
        const shouldHighlight = highlightSet.has(node.id);
        // Only update if highlight status changed
        if (node.data.isHighlighted === shouldHighlight) return node;
        return {
          ...node,
          data: { ...node.data, isHighlighted: shouldHighlight },
        };
      })
    );
  }, [highlightedNodeIds, setNodes]);

  // Highlight specific ports - only update the affected node(s)
  const prevHoveredPortRef = useRef<typeof hoveredPort>(null);
  useEffect(() => {
    const prev = prevHoveredPortRef.current;
    prevHoveredPortRef.current = hoveredPort;

    // Determine which nodes need updating
    const nodesToUpdate = new Set<string>();
    if (prev?.nodeId) nodesToUpdate.add(prev.nodeId);
    if (hoveredPort?.nodeId) nodesToUpdate.add(hoveredPort.nodeId);

    if (nodesToUpdate.size === 0) return;

    setNodes((existing) =>
      existing.map((node) => {
        if (!nodesToUpdate.has(node.id)) return node;
        const newHighlightedPort =
          hoveredPort && hoveredPort.nodeId === node.id
            ? { port: hoveredPort.port, direction: hoveredPort.direction }
            : null;
        // Only update if port highlight changed
        if (node.data.highlightedPort === newHighlightedPort) return node;
        return {
          ...node,
          data: { ...node.data, highlightedPort: newHighlightedPort },
        };
      })
    );
  }, [hoveredPort, setNodes]);

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

  // Sync edge colors with port types
  useEffect(() => {
    setEdges((eds) =>
      eds.map((edge) => {
        if (!edge.sourceHandle) return edge;
        const desiredStroke = getPortTypeColor(getPortTypeForHandle(edge.source, edge.sourceHandle, "source"));
        const currentStroke = (edge.style as React.CSSProperties | undefined)?.stroke as string | undefined;
        if (currentStroke === desiredStroke) return edge;
        return {
          ...edge,
          style: {
            ...(edge.style as React.CSSProperties | undefined),
            stroke: desiredStroke,
            strokeWidth: (edge.style as React.CSSProperties | undefined)?.strokeWidth || 2,
          },
        };
      })
    );
  }, [getPortTypeForHandle, setEdges]);

  // Update existing nodes with handlers
  useEffect(() => {
    setNodes((existing) =>
      existing.map((node) => ({
        ...node,
        data: {
          ...node.data,
          ...nodeHandlers,
        },
      }))
    );
  }, [nodeHandlers, setNodes]);

  useEffect(() => {
    if (selectedNodeId && !nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [nodes, selectedNodeId]);

  // ========== Graph operations ==========

  const buildGraphPayload = useCallback(
    (mode: "full" | "selection", targetNodes?: string[], extras?: { max_steps?: number }) => {
      const nodePayload = nodes.map((node) => ({
        id: node.id,
        type: node.data.nodeType,
        params: node.data.params,
        input_values: node.data.inputValues ?? {},
        input_ports_override: node.data.input_ports,
        input_port_types_override: node.data.input_port_types,
        output_ports_override: node.data.output_ports,
        output_port_types_override: node.data.output_port_types,
      }));

      const linkPayload = edges
        .filter((edge): edge is typeof edge & { sourceHandle: string; targetHandle: string } =>
          Boolean(edge.sourceHandle) && Boolean(edge.targetHandle))
        .map((edge) => {
          const sourceType = getPortTypeForHandle(edge.source, edge.sourceHandle!, "source");
          const targetType = getPortTypeForHandle(edge.target, edge.targetHandle!, "target");
          const isControl = sourceType.kind === "control" || targetType.kind === "control";
          return {
            from_node: edge.source,
            from_port: edge.sourceHandle,
            to_node: edge.target,
            to_port: edge.targetHandle,
            kind: isControl ? "control" : (edge.data as any)?.kind || "data",
          };
        });

      const options: Record<string, unknown> = { mode };
      if (mode === "selection" && targetNodes?.length) {
        options.target_nodes = targetNodes;
      }
      if (extras?.max_steps != null) {
        options.max_steps = extras.max_steps;
      }

      return {
        graph: { nodes: nodePayload, links: linkPayload },
        options,
      };
    },
    [edges, nodes, getPortTypeForHandle]
  );

  const handleRunGraph = useCallback(
    async (mode: "full" | "selection", targetNodes?: string[], extras?: { max_steps?: number }) => {
      if (nodes.length === 0) return;

      const runNodes = mode === "full"
        ? new Set(nodes.map((n) => n.id))
        : getDependentNodes(targetNodes || selectedNodeIds);

      setRunningNodeIds((prev) => {
        const merged = new Set(prev);
        runNodes.forEach((id) => merged.add(id));
        return merged;
      });

      const payload = buildGraphPayload(mode, targetNodes || (mode === "selection" ? selectedNodeIds : undefined), extras);

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

  const handleInterruptAll = useCallback(async () => {
    if (!executionId) return;
    try {
      await fetch(`/api/executions/${executionId}/cancel`, { method: "POST" });
    } catch (e) {
      console.error("Failed to interrupt execution:", e);
    }
  }, [executionId]);

  const handleClearBackendCache = useCallback(async () => {
    try {
      const response = await fetch("/api/cache/clear", { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        console.log(`Cleared ${data.cleared} cached entries`);
        clearAllCache();
      }
    } catch (e) {
      console.error("Failed to clear backend cache:", e);
    }
  }, [clearAllCache]);

  // ========== Selection operations ==========

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

  const handleDeleteSelected = useCallback(() => {
    if (selectedNodeIds.length === 0 && selectedEdgeIds.length === 0) return;

    takeSnapshot();

    if (selectedNodeIds.length > 0) {
      setNodes((current) => current.filter((node) => !selectedNodeIds.includes(node.id)));
    }

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
  }, [selectedNodeIds, selectedEdgeIds, setNodes, setEdges, takeSnapshot]);

  const handleDuplicateSelected = useCallback(() => {
    if (selectedNodeIds.length === 0) return;

    takeSnapshot();

    const selectedNodeSet = new Set(selectedNodeIds);
    const selectedNodesArray = nodes.filter((node) => selectedNodeSet.has(node.id));
    const newNodes: Node<BlueprintNodeData>[] = [];
    const nodeIdMap = new Map<string, string>();

    selectedNodesArray.forEach((node) => {
      if (!node.data.metadata) return;
      const newNode = createNodeFromType(
        node.data.metadata,
        { x: node.position.x + 50, y: node.position.y + 50 },
        nodeHandlers
      );
      nodeIdMap.set(node.id, newNode.id);
      newNodes.push({
        ...newNode,
        data: {
          ...newNode.data,
          params: { ...node.data.params },
          inputValues: { ...node.data.inputValues },
        },
      });
    });

    const edgesToCopy = edges.filter((edge) =>
      selectedNodeSet.has(edge.source) || selectedNodeSet.has(edge.target)
    );
    const newEdges: Edge[] = [];
    const existingEdges = [...edges];
    const isDuplicateEdge = (edge: Edge, list: Edge[]) =>
      list.some(
        (item) =>
          item.source === edge.source &&
          item.target === edge.target &&
          item.sourceHandle === edge.sourceHandle &&
          item.targetHandle === edge.targetHandle
      );

    edgesToCopy.forEach((edge) => {
      const source = nodeIdMap.get(edge.source) ?? edge.source;
      const target = nodeIdMap.get(edge.target) ?? edge.target;
      const newEdge = {
        ...edge,
        id: `edge-${Math.random().toString(36).slice(2, 10)}`,
        source,
        target,
        selected: false,
      };
      if (!isDuplicateEdge(newEdge, existingEdges) && !isDuplicateEdge(newEdge, newEdges)) {
        newEdges.push(newEdge);
      }
    });

    setNodes((current) => [...current, ...newNodes]);
    if (newEdges.length > 0) {
      setEdges((current) => [...current, ...newEdges]);
    }

    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
    setSelectedEdgeIds(newEdges.map((edge) => edge.id));
  }, [selectedNodeIds, nodes, edges, createNodeFromType, nodeHandlers, setNodes, setEdges, takeSnapshot]);

  const handleCopy = useCallback(() => {
    if (selectedNodeIds.length === 0) return;
    const selectedNodesArray = nodes.filter((node) => selectedNodeIds.includes(node.id));
    setClipboard(selectedNodesArray);
  }, [selectedNodeIds, nodes]);

  const handlePaste = useCallback(() => {
    if (!clipboard || clipboard.length === 0) return;

    takeSnapshot();

    const newNodes: Node<BlueprintNodeData>[] = [];

    clipboard.forEach((node) => {
      if (!node.data.metadata) return;
      const newNode = createNodeFromType(
        node.data.metadata,
        { x: node.position.x + 80, y: node.position.y + 80 },
        nodeHandlers
      );
      newNodes.push({
        ...newNode,
        data: {
          ...newNode.data,
          params: { ...node.data.params },
          inputValues: { ...node.data.inputValues },
        },
      });
    });

    setNodes((current) => [...current, ...newNodes]);

    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
  }, [clipboard, createNodeFromType, nodeHandlers, setNodes, takeSnapshot]);

  const handleSelectAll = useCallback(() => {
    const allNodeIds = nodes.map((n) => n.id);
    const allEdgeIds = edges.map((e) => e.id);
    setSelectedNodeIds(allNodeIds);
    setSelectedEdgeIds(allEdgeIds);
    setSelectedNodeId(allNodeIds[0] ?? null);
    setNodes((nds) => nds.map((node) => ({ ...node, selected: true })));
    setEdges((eds) => eds.map((edge) => ({ ...edge, selected: true })));
  }, [nodes, edges, setNodes, setEdges]);

  // ========== Keyboard shortcuts ==========

  useKeyboardShortcuts({
    onDelete: handleDeleteSelected,
    onSelectAll: handleSelectAll,
    onDuplicate: handleDuplicateSelected,
    onCopy: handleCopy,
    onPaste: handlePaste,
    onUndo: undo,
    onRedo: redo,
    canDuplicate: selectedNodeIds.length > 0,
    canCopy: selectedNodeIds.length > 0,
  });

  // ========== Node adding ==========

  const handleAddNode = useCallback(
    (nodeType: NodeTypeDefinition) => {
      takeSnapshot();
      const position = { x: 120 + nodes.length * 36, y: 80 + nodes.length * 32 };
      const newNode = createNodeFromType(nodeType, position, nodeHandlers);
      setNodes((existing) => existing.concat(newNode));
    },
    [createNodeFromType, nodeHandlers, nodes.length, setNodes, takeSnapshot]
  );

  // ========== Connection handling ==========

  const handleConnect = useCallback(
    (connection: Parameters<typeof addEdge>[0]) => {
      if (!connection.sourceHandle || !connection.targetHandle) return;

      const normalized = normalizeConnection(connection as Connection);
      const validation = validateConnection(normalized, {
        setConnectionLineIsInvalid,
        setConnectionLineColor,
        setConnectionLineDash,
      });
      if (!validation.valid) {
        showConnectionMessage(validation.reason || "These connectors cannot be linked");
        return;
      }

      const sourceType = getPortTypeForHandle(normalized.source!, normalized.sourceHandle!, "source");
      const edgeColor = getPortTypeColor(sourceType);

      const isDuplicate = edges.some(
        (edge) =>
          edge.source === normalized.source &&
          edge.target === normalized.target &&
          edge.sourceHandle === normalized.sourceHandle &&
          edge.targetHandle === normalized.targetHandle
      );

      if (isDuplicate) {
        connectSucceededRef.current = true;
        return;
      }

      connectSucceededRef.current = true;
      takeSnapshot();

      setEdges((existing) => {
        const filtered = existing.filter(
          (edge) =>
            !(edge.target === normalized.target && edge.targetHandle === normalized.targetHandle)
        );

        return addEdge(
          {
            ...normalized,
            type: "default",
            animated: false,
            style: { stroke: edgeColor, strokeWidth: 2 },
          },
          filtered
        );
      });
      setConnectionLineIsInvalid(false);
    },
    [edges, getPortTypeForHandle, normalizeConnection, setEdges, showConnectionMessage, takeSnapshot, validateConnection]
  );

  const isValidConnection = useCallback(
    (connection: Connection) => validateConnection(connection).valid,
    [validateConnection]
  );

  const onConnectStart = useCallback(
    (_: unknown, { nodeId, handleId, handleType }: { nodeId: string | null; handleId: string | null; handleType: "source" | "target" | null }) => {
      setConnectStartParams({ nodeId, handleId, handleType });
      if (nodeId && handleId && handleType) {
        const type = handleType === "source"
          ? getPortTypeForHandle(nodeId, handleId, "source")
          : getPortTypeForHandle(nodeId, handleId, "target");
        setConnectionLineColor(getPortTypeColor(type));
        setConnectionLineIsInvalid(false);
      } else {
        setConnectionLineColor(undefined);
        setConnectionLineIsInvalid(false);
      }
    },
    [getPortTypeForHandle]
  );

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent) => {
      if (connectSucceededRef.current) {
        connectSucceededRef.current = false;
        return;
      }
      const target = event.target;
      const isPane = target instanceof HTMLElement ? Boolean(target.closest(".react-flow__pane")) : false;
      const isHandle = target instanceof HTMLElement ? Boolean(target.closest(".react-flow__handle")) : false;
      const isNode = target instanceof HTMLElement ? Boolean(target.closest(".react-flow__node")) : false;
      const isEdge = target instanceof HTMLElement ? Boolean(target.closest(".react-flow__edge")) : false;
      const isEmptySpace = isPane && !isHandle && !isNode && !isEdge;

      if (isEmptySpace && connectStartParams?.nodeId && connectStartParams?.handleId && reactFlowInstance) {
        const { clientX, clientY } = "changedTouches" in event ? event.changedTouches[0] : (event as MouseEvent);

        const flowPosition = reactFlowInstance.screenToFlowPosition({ x: clientX, y: clientY });

        const sourceRole = connectStartParams.handleType || "source";
        const sourcePortType = getPortTypeForHandle(
          connectStartParams.nodeId,
          connectStartParams.handleId,
          sourceRole
        );

        openSmartConnect(
          { x: clientX, y: clientY },
          flowPosition,
          {
            nodeId: connectStartParams.nodeId,
            handleId: connectStartParams.handleId,
            type: connectStartParams.handleType || "source",
          },
          sourcePortType
        );
      }

      setConnectStartParams(null);
      setConnectionLineColor(undefined);
      setConnectionLineIsInvalid(false);
    },
    [connectStartParams, reactFlowInstance, getPortTypeForHandle, openSmartConnect]
  );

  // ========== Smart connect select ==========

  const handleSmartConnectSelect = useCallback(
    (nodeType: NodeTypeDefinition) => {
      if (!smartConnectMenu.source) return;

      takeSnapshot();

      const { flowPosition, source } = smartConnectMenu;
      const compatiblePort = findCompatiblePortForSmartConnect(nodeType, source);
      if (!compatiblePort) {
        showConnectionMessage("No compatible ports found for this node");
        closeSmartConnect();
        return;
      }

      // Calculate position to align the connecting handle
      const { input_ports } = nodeType.node_type === "core.container.make_array"
        ? { input_ports: ["control_in", "item_0"] }
        : { input_ports: nodeType.input_ports };

      const matchedPortIndex = source.type === "source"
        ? input_ports.indexOf(compatiblePort.targetHandle!)
        : nodeType.output_ports.indexOf(compatiblePort.sourceHandle!);
      const resolvedPortIndex = matchedPortIndex >= 0 ? matchedPortIndex : 0;
      const portYOffset = getPortYOffset(resolvedPortIndex);

      const extraInputRows = nodeType.node_type === "core.container.make_array" ? 1 : 0;
      const maxPorts = Math.max(input_ports.length + extraInputRows, nodeType.output_ports.length);
      const paramCount = Object.keys(nodeType.params_schema ?? {}).length;
      const { width: initialWidth } = computeNodeDimensions(maxPorts, { paramCount });

      let xOffset = 0;
      if (source.type === "source") {
        xOffset = 0;
      } else {
        xOffset = initialWidth;
      }

      const newNode = createNodeFromType(
        nodeType,
        { x: flowPosition.x - xOffset, y: flowPosition.y - portYOffset },
        nodeHandlers
      );

      setNodes((nds) => nds.concat(newNode));

      // Create connection
      let sourceId, sourceHandle, targetId, targetHandle;

      if (source.type === "source") {
        sourceId = source.nodeId;
        sourceHandle = source.handleId;
        targetId = newNode.id;
        targetHandle = compatiblePort.targetHandle;
      } else {
        sourceId = newNode.id;
        sourceHandle = compatiblePort.sourceHandle;
        targetId = source.nodeId;
        targetHandle = source.handleId;
      }

      if (sourceHandle && targetHandle) {
        const sourceType = compatiblePort.sourceType;
        const targetType = compatiblePort.targetType;

        if (arePortTypesCompatible(sourceType, targetType)) {
          const edgeColor = getPortTypeColor(sourceType);
          setEdges((eds) => {
            const filtered = source.type === "target"
              ? eds.filter((edge) => !(edge.target === targetId && edge.targetHandle === targetHandle))
              : eds;
            return addEdge(
              {
                source: sourceId,
                sourceHandle: sourceHandle,
                target: targetId,
                targetHandle: targetHandle,
                type: "default",
                animated: false,
                style: { stroke: edgeColor, strokeWidth: 2 },
              },
              filtered
            );
          });
        }
      }

      closeSmartConnect();
    },
    [smartConnectMenu, createNodeFromType, nodeHandlers, setNodes, setEdges, arePortTypesCompatible, findCompatiblePortForSmartConnect, closeSmartConnect, showConnectionMessage, takeSnapshot, getPortYOffset]
  );

  // ========== Handle position for smart connect line ==========

  const getHandlePosition = useCallback((nodeId: string, handleId: string, type: "source" | "target") => {
    if (reactFlowInstance) {
      const escapeId = (value: string) =>
        typeof CSS !== "undefined" && typeof CSS.escape === "function"
          ? CSS.escape(value)
          : value.replace(/["\\]/g, "\\$&");
      const safeNodeId = escapeId(nodeId);
      const safeHandleId = escapeId(handleId);
      const handlePosition = type === "target" ? "left" : "right";
      const selectors = [
        `.react-flow__node[data-id="${safeNodeId}"] .react-flow__handle-${type}[data-handleid="${safeHandleId}"]`,
        `.react-flow__node[data-id="${safeNodeId}"] .react-flow__handle.${type}[data-handleid="${safeHandleId}"]`,
        `.react-flow__node[data-id="${safeNodeId}"] .react-flow__handle[data-handleid="${safeHandleId}"][data-handlepos="${handlePosition}"]`,
        `.react-flow__node[data-id="${safeNodeId}"] .react-flow__handle[data-handleid="${safeHandleId}"]`,
      ];
      const handleEl = selectors
        .map((selector) => document.querySelector(selector))
        .find((el): el is HTMLElement => Boolean(el)) ?? null;
      if (handleEl) {
        const rect = handleEl.getBoundingClientRect();
        const center = { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
        return reactFlowInstance.screenToFlowPosition(center);
      }
    }

    const node = nodes.find((n) => n.id === nodeId);
    if (!node) return null;

    const isInput = type === "target";
    const ports = isInput ? node.data.input_ports : node.data.output_ports;
    const index = ports.indexOf(handleId);

    if (index === -1) return null;

    const yOffset = HEADER_HEIGHT + index * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2;
    const nodeWidth = node.width ?? MIN_NODE_WIDTH;

    return {
      x: node.position.x + (isInput ? 0 : nodeWidth),
      y: node.position.y + yOffset,
    };
  }, [nodes, reactFlowInstance]);

  // ========== Edge selection ==========

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

  const findIntersectingEdges = useCallback((
    box: { startX: number; startY: number; endX: number; endY: number },
    viewport: { x: number; y: number; zoom: number }
  ): string[] => {
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

    if (rw < 5 && rh < 5) return [];

    const intersectingEdgeIds: string[] = [];

    edges.forEach((edge) => {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);

      if (!sourceNode || !targetNode) return;

      const sourceX = sourceNode.position.x + (sourceNode.width || MIN_NODE_WIDTH);
      const sourceParamCount = Object.keys(sourceNode.data.metadata?.params_schema ?? {}).length;
      const sourceMaxPorts = Math.max(sourceNode.data.input_ports.length, sourceNode.data.output_ports.length);
      const sourceFallbackHeight = computeNodeDimensions(sourceMaxPorts, { paramCount: sourceParamCount }).height;
      const sourceY = sourceNode.position.y + (sourceNode.height || sourceFallbackHeight) / 2;
      const targetX = targetNode.position.x;
      const targetParamCount = Object.keys(targetNode.data.metadata?.params_schema ?? {}).length;
      const targetMaxPorts = Math.max(targetNode.data.input_ports.length, targetNode.data.output_ports.length);
      const targetFallbackHeight = computeNodeDimensions(targetMaxPorts, { paramCount: targetParamCount }).height;
      const targetY = targetNode.position.y + (targetNode.height || targetFallbackHeight) / 2;

      if (bezierIntersectsRect(sourceX, sourceY, targetX, targetY, rx, ry, rw, rh)) {
        intersectingEdgeIds.push(edge.id);
      }
    });

    return intersectingEdgeIds;
  }, [edges, nodes]);

  const updatePreviewEdges = useCallback((box: { startX: number; startY: number; endX: number; endY: number }) => {
    const viewport = getViewport();
    const intersectingEdges = findIntersectingEdges(box, viewport);
    setPreviewEdgeIds(intersectingEdges);
  }, [getViewport, findIntersectingEdges]);

  const handleSelectionEnd = useCallback(() => {
    if (previewEdgeIds.length > 0) {
      setSelectedEdgeIds((prev) => {
        const combined = new Set([...prev, ...previewEdgeIds]);
        return Array.from(combined);
      });
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

  // ========== Mouse handlers ==========

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      const target = e.target;
      if (target instanceof HTMLElement && target.classList.contains('react-flow__pane')) {
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
        updatePreviewEdges(newBox);
      }
    }
  }, [isSelecting, selectionBox, updatePreviewEdges]);

  const handleMouseUp = useCallback(() => {
    if (isSelecting) {
      handleSelectionEnd();
    }
  }, [isSelecting, handleSelectionEnd]);

  // ========== Drag and drop ==========

  const handleDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
  }, []);

  const handleDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();

      const typeData = event.dataTransfer.getData("application/reactflow");
      if (!typeData) return;

      const nodeType: NodeTypeDefinition = JSON.parse(typeData);
      if (!nodeType) return;

      const position = reactFlowInstance?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      if (!position) return;

      takeSnapshot();

      const newNode = createNodeFromType(nodeType, position, nodeHandlers);
      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance, createNodeFromType, nodeHandlers, setNodes, takeSnapshot]
  );

  // ========== Highlight handler ==========

  const handleHighlightNodes = useCallback((nodeIds: string[]) => {
    setHighlightedNodeIds(nodeIds);
  }, []);

  // ========== Render ==========

  return (
    <PopupProvider>
      <ReactFlowProvider>
        <div className="app-shell">
          {/* Keep both views mounted, use CSS to hide inactive view for instant switching */}
          <div
            className="reactflow-fullpage"
            ref={reactFlowWrapper}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            style={{ display: headerTab === "graph-editor" ? "block" : "none" }}
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
              isValidConnection={isValidConnection}
              connectionLineStyle={{
                stroke: connectionLineColor || "#4a9eff",
                strokeWidth: connectionLineIsInvalid ? 3.2 : 2.5,
                strokeDasharray: connectionLineDash,
              }}
              connectionLineComponent={TypeAwareConnectionLine}
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
            <ConnectionToast message={connectionMessage} />
          </div>
          <div
            className="outputs-fullpage"
            style={{ display: headerTab === "outputs" ? "block" : "none" }}
          >
            <OutputsView nodes={nodes} outputs={outputs} />
          </div>

          <AppHeader
            headerTab={headerTab}
            onTabChange={setHeaderTab}
            graphSummary={graphSummary}
            outputsSummary={outputsSummary}
            isRunning={isRunning}
            isConnected={isConnected}
            progress={progress}
            error={error}
            executionId={executionId}
            nodesCount={nodes.length}
            onRunGraph={() => handleRunGraph("full")}
            onInterruptAll={handleInterruptAll}
            onClearCache={handleClearBackendCache}
          />

          {headerTab === "graph-editor" && (
            <>
              <aside
                className={`side-panel left-panel ${leftPanelCollapsed ? "collapsed" : ""}`}
                style={{ width: leftPanelCollapsed ? 0 : leftPanelWidth }}
              >
                {!leftPanelCollapsed && (
                  <>
                    <NodePalette nodeTypes={nodeLibrary} onAddNode={handleAddNode} />
                    <div
                      className="resize-handle right"
                      onMouseDown={startResizingLeft}
                    />
                  </>
                )}
              </aside>

              <button
                className="panel-collapse-btn left"
                style={{ left: leftPanelCollapsed ? 0 : leftPanelWidth }}
                onClick={toggleLeftPanel}
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
                      onMouseDown={startResizingRight}
                    />
                    <div className="right-panel-content">
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

                      {(selectedNodeIds.length > 1 || selectedEdgeIds.length > 0) && (
                        <div className="multi-select-toolbar">
                          <span className="selection-count">
                            {selectedNodeIds.length > 0 && `${selectedNodeIds.length} node${selectedNodeIds.length !== 1 ? "s" : ""}`}
                            {selectedNodeIds.length > 0 && selectedEdgeIds.length > 0 && ", "}
                            {selectedEdgeIds.length > 0 && `${selectedEdgeIds.length} edge${selectedEdgeIds.length !== 1 ? "s" : ""}`}
                            {" "}selected
                          </span>
                          <div className="toolbar-actions">
                            {selectedNodeIds.length > 0 && (
                              <>
                                <button
                                  type="button"
                                  className="toolbar-btn"
                                  onClick={handleDuplicateSelected}
                                  title="Duplicate (Ctrl+D)"
                                >
                                  <CopyIcon />
                                  Duplicate
                                </button>
                                <button
                                  type="button"
                                  className="toolbar-btn"
                                  onClick={handleCopy}
                                  title="Copy (Ctrl+C)"
                                >
                                  <CopyIcon />
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
                              <DeleteIcon />
                              Delete
                            </button>
                          </div>
                        </div>
                      )}

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
                            hoveredPort={hoveredPort}
                            onPortHover={(info) => setHoveredPort(info)}
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
                onClick={toggleRightPanel}
                title={rightPanelCollapsed ? "Expand Logs" : "Collapse Logs"}
              >
                {rightPanelCollapsed ? <ChevronLeft /> : <ChevronRight />}
              </button>
            </>
          )}

          <SmartConnectLine
            isOpen={smartConnectMenu.isOpen}
            source={smartConnectMenu.source}
            position={smartConnectMenu.position}
            getHandlePosition={getHandlePosition}
            reactFlowInstance={reactFlowInstance}
          />

          <SmartConnectModal
            isOpen={smartConnectMenu.isOpen}
            position={smartConnectMenu.position}
            onClose={closeSmartConnect}
            onSelect={handleSmartConnectSelect}
            nodeTypes={smartConnectNodeTypes}
            sourceHandleType={smartConnectMenu.source?.type}
            sourcePortKind={smartConnectMenu.sourcePortKind}
          />
        </div>
      </ReactFlowProvider>
    </PopupProvider>
  );
};

export default App;
