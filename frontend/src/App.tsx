import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  Controls,
  Connection,
  MiniMap,
  Node,
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
import { PopupProvider } from "./context/PopupContext";
import { useGraphExecution } from "./hooks/useGraphExecution";
import { useUndoRedo } from "./hooks/useUndoRedo";
import {
  BlueprintNodeData,
  NodeTypeDefinition,
} from "./types";
import {
  MIN_NODE_WIDTH,
  bezierIntersectsRect,
  computeNodeDimensions,
  formatPortTypeLabel,
  getPortTypeColor,
  HEADER_HEIGHT,
  PORT_ROW_HEIGHT,
} from "./graph/utils";

type RightPanelTab = "inspector" | "execution";

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
  const [hoveredPort, setHoveredPort] = useState<{ nodeId: string; port: string; direction: "input" | "output" } | null>(null);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const nodeIdRef = useRef(1);

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
  const [connectionMessage, setConnectionMessage] = useState<{ text: string; tone: "error" | "info" } | null>(null);
  const connectionMessageTimeout = useRef<number | null>(null);
  const [connectionLineColor, setConnectionLineColor] = useState<string | undefined>(undefined);
  const [connectionLineIsInvalid, setConnectionLineIsInvalid] = useState(false);
  const connectSucceededRef = useRef(false);

  // Ensure connection toast timers are cleaned up
  useEffect(() => {
    return () => {
      if (connectionMessageTimeout.current) {
        window.clearTimeout(connectionMessageTimeout.current);
      }
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
  const nodeMap = useMemo(() => new Map(nodes.map((node) => [node.id, node])), [nodes]);

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

  const outputsSummary = useMemo(() => {
    let images = 0;
    let streams = 0;
    let values = 0;

    for (const node of nodes) {
      const display = node.data.last_outputs?.display;
      if (typeof display === "string" && display.startsWith("data:image")) {
        images += 1;
      }
    }

    for (const [key, value] of Object.entries(outputs)) {
      if (typeof value === "string" && value.startsWith("data:image")) {
        images += 1;
      } else if (typeof value === "string" && key.toLowerCase().includes("stream_id")) {
        streams += 1;
      } else {
        values += 1;
      }
    }

    return { images, streams, values };
  }, [nodes, outputs]);

  const graphSummary = useMemo(() => {
    const nodeCount = nodes.length;
    const edgeCount = edges.length;
    const selectedCount = selectedNodeIds.length + selectedEdgeIds.length;
    return { nodeCount, edgeCount, selectedCount };
  }, [nodes.length, edges.length, selectedNodeIds.length, selectedEdgeIds.length]);

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
      const sourceX = sourceNode.position.x + (sourceNode.width || MIN_NODE_WIDTH);
      const sourceY = sourceNode.position.y + (sourceNode.height || computeNodeDimensions(Math.max(sourceNode.data.input_ports.length, sourceNode.data.output_ports.length)).height) / 2;
      const targetX = targetNode.position.x;
      const targetY = targetNode.position.y + (targetNode.height || computeNodeDimensions(Math.max(targetNode.data.input_ports.length, targetNode.data.output_ports.length)).height) / 2;

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

  // Highlight specific ports (from inspector or node hover)
  useEffect(() => {
    setNodes((existing) =>
      existing.map((node) => ({
        ...node,
        data: {
          ...node.data,
          highlightedPort:
            hoveredPort && hoveredPort.nodeId === node.id
              ? { port: hoveredPort.port, direction: hoveredPort.direction }
              : null,
        },
      }))
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
          onPortHover: setHoveredPort,
        },
      });
    });

    setNodes((current) => [...current, ...newNodes]);

    // Select the new nodes
    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
  }, [selectedNodeIds, nodes, handleDeleteNode, handleRunFromNode, handleClearNodeCache, handleInterruptNode, setNodes]);

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
          onPortHover: setHoveredPort,
        },
      });
    });

    setNodes((current) => [...current, ...newNodes]);

    // Select the new nodes
    const newIds = newNodes.map((n) => n.id);
    setSelectedNodeIds(newIds);
    setSelectedNodeId(newIds[0] ?? null);
  }, [clipboard, handleDeleteNode, handleRunFromNode, handleClearNodeCache, handleInterruptNode, setNodes]);

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
      const { width: initialWidth, height: initialHeight } = computeNodeDimensions(maxPorts);

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
          input_port_types: nodeType.input_port_types,
          output_port_types: nodeType.output_port_types,
          params,
          breakpoint: false,
          metadata: nodeType,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
          onPortHover: setHoveredPort,
          width: initialWidth,
          height: initialHeight,
          executionLogs: [],
        },
      };
      setNodes((existing) => existing.concat(payload));
    },
    [handleDeleteNode, handleRunFromNode, handleClearNodeCache, handleInterruptNode, nodes.length, setNodes]
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
          onPortHover: setHoveredPort,
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

  const showConnectionMessage = useCallback((text: string, tone: "error" | "info" = "error") => {
    if (connectionMessageTimeout.current) {
      window.clearTimeout(connectionMessageTimeout.current);
    }
    setConnectionMessage({ text, tone });
    connectionMessageTimeout.current = window.setTimeout(() => setConnectionMessage(null), 1800);
  }, []);

  const arePortTypesCompatible = useCallback((sourceType: string, targetType: string) => {
    const src = (sourceType || "any").toLowerCase();
    const tgt = (targetType || "any").toLowerCase();
    return src === "any" || tgt === "any" || src === tgt;
  }, []);

  const getHandleRole = useCallback(
    (nodeId: string, handleId: string): "source" | "target" | null => {
      const node = nodeMap.get(nodeId);
      if (!node) return null;
      if (node.data.output_ports.includes(handleId)) return "source";
      if (node.data.input_ports.includes(handleId)) return "target";
      return null;
    },
    [nodeMap]
  );

  const getPortTypeForHandle = useCallback(
    (nodeId: string, handleId: string, role: "source" | "target") => {
      const node = nodeMap.get(nodeId);
      if (!node) return "any";
      const map =
        role === "source"
          ? node.data.output_port_types || node.data.metadata?.output_port_types
          : node.data.input_port_types || node.data.metadata?.input_port_types;
      return map?.[handleId] || "any";
    },
    [nodeMap]
  );

  const findCompatiblePortForSmartConnect = useCallback(
    (nodeType: NodeTypeDefinition, source: { nodeId: string; handleId: string; type: "source" | "target" }) => {
      if (source.type === "source") {
        const sourceType = getPortTypeForHandle(source.nodeId, source.handleId, "source");
        for (const port of nodeType.input_ports) {
          const targetType = nodeType.input_port_types?.[port] || "any";
          if (arePortTypesCompatible(sourceType, targetType)) {
            return { targetHandle: port, sourceType, targetType };
          }
        }
        return null;
      }

      const targetType = getPortTypeForHandle(source.nodeId, source.handleId, "target");
      for (const port of nodeType.output_ports) {
        const sourceType = nodeType.output_port_types?.[port] || "any";
        if (arePortTypesCompatible(sourceType, targetType)) {
          return { sourceHandle: port, sourceType, targetType };
        }
      }
      return null;
    },
    [arePortTypesCompatible, getPortTypeForHandle]
  );

  const normalizeConnection = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.target || !connection.sourceHandle || !connection.targetHandle) {
        return connection;
      }

      const sourceRole = getHandleRole(connection.source, connection.sourceHandle);
      const targetRole = getHandleRole(connection.target, connection.targetHandle);

      if (sourceRole === "target" && targetRole === "source") {
        return {
          ...connection,
          source: connection.target,
          sourceHandle: connection.targetHandle,
          target: connection.source,
          targetHandle: connection.sourceHandle,
        };
      }

      return connection;
    },
    [getHandleRole]
  );

  const validateConnection = useCallback(
    (connection: Connection) => {
      if (!connection.source || !connection.sourceHandle) {
        setConnectionLineIsInvalid(false);
        return { valid: false, reason: "Select both connectors" };
      }

      if (!connection.target || !connection.targetHandle) {
        const sourceRole = getHandleRole(connection.source, connection.sourceHandle);
        const sourceType = getPortTypeForHandle(
          connection.source,
          connection.sourceHandle,
          sourceRole === "target" ? "target" : "source"
        );
        setConnectionLineIsInvalid(false);
        return { valid: true, sourceType };
      }

      const normalized = normalizeConnection(connection);
      const sourceRole = getHandleRole(normalized.source!, normalized.sourceHandle!);
      const targetRole = getHandleRole(normalized.target!, normalized.targetHandle!);

      if (sourceRole !== "source" || targetRole !== "target") {
        setConnectionLineIsInvalid(true);
        return { valid: false, reason: "Connect outputs to inputs only" };
      }

      if (normalized.source === normalized.target) {
        setConnectionLineIsInvalid(true);
        return { valid: false, reason: "Cannot connect a node to itself" };
      }

      const sourceType = getPortTypeForHandle(normalized.source!, normalized.sourceHandle!, "source");
      const targetType = getPortTypeForHandle(normalized.target!, normalized.targetHandle!, "target");
      const compatible = arePortTypesCompatible(sourceType, targetType);

      setConnectionLineIsInvalid(!compatible);
      const desiredColor = getPortTypeColor(sourceType);
      if (connectionLineColor !== desiredColor) {
        setConnectionLineColor(desiredColor);
      }

      return {
        valid: compatible,
        reason: compatible ? undefined : `Type mismatch: ${formatPortTypeLabel(sourceType)} -> ${formatPortTypeLabel(targetType)}`,
        sourceType,
        targetType,
      };
    },
    [arePortTypesCompatible, connectionLineColor, getHandleRole, getPortTypeForHandle, normalizeConnection]
  );

  const handleConnect = useCallback(
    (connection: Parameters<typeof addEdge>[0]) => {
      if (!connection.sourceHandle || !connection.targetHandle) return;

      const normalized = normalizeConnection(connection as Connection);
      const validation = validateConnection(normalized);
      if (!validation.valid) {
        showConnectionMessage(validation.reason || "These connectors cannot be linked");
        return;
      }

      const sourceType = getPortTypeForHandle(normalized.source!, normalized.sourceHandle!, "source");
      const edgeColor = getPortTypeColor(sourceType);

      // Check for duplicate edges (same source, target, sourceHandle, targetHandle)
      const isDuplicate = edges.some(
        (edge) =>
          edge.source === normalized.source &&
          edge.target === normalized.target &&
          edge.sourceHandle === normalized.sourceHandle &&
          edge.targetHandle === normalized.targetHandle
      );

      if (isDuplicate) {
        connectSucceededRef.current = true;
        return; // Don't add duplicate edge
      }

      connectSucceededRef.current = true;
      takeSnapshot();

      setEdges((existing) => {
        // Remove any existing edge that connects to the same target handle
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

  const isValidConnection = useCallback((connection: Connection) => validateConnection(connection).valid, [validateConnection]);

  const smartConnectNodeTypes = useMemo(() => {
    if (!smartConnectMenu.source) return nodeLibrary;
    return nodeLibrary.filter((nodeType) =>
      Boolean(findCompatiblePortForSmartConnect(nodeType, smartConnectMenu.source!))
    );
  }, [findCompatiblePortForSmartConnect, nodeLibrary, smartConnectMenu.source]);

  // Ensure all edges carry a color that matches their source port type
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

  // Helper to calculate handle position for smart connect line
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

    // Matches BlueprintNode layout constants
    const yOffset = HEADER_HEIGHT + index * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2;

    // Use measured width if available, otherwise fallback
    const nodeWidth = node.width ?? MIN_NODE_WIDTH;

    return {
      x: node.position.x + (isInput ? 0 : nodeWidth),
      y: node.position.y + yOffset,
    };
  }, [nodes, reactFlowInstance]);

  const onConnectStart = useCallback((_: unknown, { nodeId, handleId, handleType }: { nodeId: string | null; handleId: string | null; handleType: "source" | "target" | null }) => {
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
  }, [getPortTypeForHandle]);

    const onConnectEnd = useCallback(
      (event: MouseEvent | TouchEvent) => {
        if (connectSucceededRef.current) {
          connectSucceededRef.current = false;
          return;
        }
        const target = event.target;
        const isPane =
          target instanceof HTMLElement
            ? Boolean(target.closest(".react-flow__pane"))
            : false;
        const isHandle =
          target instanceof HTMLElement
            ? Boolean(target.closest(".react-flow__handle"))
            : false;
        const isNode =
          target instanceof HTMLElement
            ? Boolean(target.closest(".react-flow__node"))
            : false;
        const isEdge =
          target instanceof HTMLElement
            ? Boolean(target.closest(".react-flow__edge"))
            : false;
        const isEmptySpace = isPane && !isHandle && !isNode && !isEdge;

        if (isEmptySpace && connectStartParams?.nodeId && connectStartParams?.handleId && reactFlowInstance) {
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
      setConnectionLineColor(undefined);
      setConnectionLineIsInvalid(false);
    },
    [connectStartParams, reactFlowInstance]
  );

  const handleSmartConnectSelect = useCallback(
    (nodeType: NodeTypeDefinition) => {
      if (!smartConnectMenu.source) return;

      takeSnapshot();

      const { flowPosition, source } = smartConnectMenu;
      const newId = `node-${nodeIdRef.current++}`;

      const compatiblePort = findCompatiblePortForSmartConnect(nodeType, source);
      if (!compatiblePort) {
        showConnectionMessage("No compatible ports found for this node");
        setSmartConnectMenu((prev) => ({ ...prev, isOpen: false }));
        return;
      }

      // Create new node
      const params: Record<string, unknown> = {};
      const defaults = nodeType.params_defaults ?? {};
      for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
        params[key] = schema.default ?? defaults[key] ?? "";
      }

      const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
      const { width: initialWidth, height: initialHeight } = computeNodeDimensions(maxPorts);

      // Calculate position to align the connecting handle with the drop location
      let xOffset = 0;
      let yOffset = 0;

      // Header ~50px, Port stride ~26px, Handle center +10px
      const matchedPortIndex = source.type === "source"
        ? nodeType.input_ports.indexOf(compatiblePort.targetHandle!)
        : nodeType.output_ports.indexOf(compatiblePort.sourceHandle!);
      const resolvedPortIndex = matchedPortIndex >= 0 ? matchedPortIndex : 0;
      const portYOffset = HEADER_HEIGHT + resolvedPortIndex * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2;

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
          input_port_types: nodeType.input_port_types,
          output_port_types: nodeType.output_port_types,
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
          onPortHover: setHoveredPort,
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
        targetHandle = compatiblePort.targetHandle; // Connect to compatible input
      } else {
        sourceId = newId;
        sourceHandle = compatiblePort.sourceHandle; // Connect from compatible output
        targetId = source.nodeId;
        targetHandle = source.handleId;
      }

      if (sourceHandle && targetHandle) {
        const sourceType = compatiblePort.sourceType;
        const targetType = compatiblePort.targetType;

        if (!arePortTypesCompatible(sourceType, targetType)) {
          showConnectionMessage(
            `Incompatible: ${formatPortTypeLabel(sourceType)} -> ${formatPortTypeLabel(targetType)}`
          );
        } else {
          const edgeColor = getPortTypeColor(sourceType);
          setEdges((eds) => {
            const filtered =
              source.type === "target"
                ? eds.filter(
                    (edge) =>
                      !(edge.target === targetId && edge.targetHandle === targetHandle)
                  )
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

      setSmartConnectMenu((prev) => ({ ...prev, isOpen: false }));
    },
      [
        smartConnectMenu,
        handleDeleteNode,
        handleRunFromNode,
        handleClearNodeCache,
        handleInterruptNode,
        setNodes,
        setEdges,
        arePortTypesCompatible,
        findCompatiblePortForSmartConnect,
        showConnectionMessage,
      ]
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
      const target = e.target;
      // Only start selection on the pane background
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
      const { width: initialWidth, height: initialHeight } = computeNodeDimensions(maxPorts);

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
          input_port_types: nodeType.input_port_types,
          output_port_types: nodeType.output_port_types,
          params,
          breakpoint: false,
          metadata: nodeType,
          onDelete: handleDeleteNode,
          onRunSelection: handleRunFromNode,
          onClearCache: handleClearNodeCache,
          onInterrupt: handleInterruptNode,
          onPortHover: setHoveredPort,
          width: initialWidth,
          height: initialHeight,
          executionLogs: [],
        },
      };

      setNodes((nds) => nds.concat(newNode));
    },
    [reactFlowInstance, setNodes, handleDeleteNode, handleRunFromNode, handleClearNodeCache, handleInterruptNode]
  );

  return (
    <PopupProvider>
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
              isValidConnection={isValidConnection}
              connectionLineStyle={{
                stroke: connectionLineColor || "#4a9eff",
                strokeWidth: connectionLineIsInvalid ? 3.2 : 2.5,
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
          {connectionMessage && (
            <div className={`connection-toast ${connectionMessage.tone}`}>
              <span className="connection-toast-dot" />
              <span className="connection-toast-text">{connectionMessage.text}</span>
            </div>
          )}
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
            {headerTab === "graph-editor" && (
              <div className="outputs-pills header-pills">
                <span className="pill">{graphSummary.nodeCount} node{graphSummary.nodeCount === 1 ? "" : "s"}</span>
                <span className="pill">{graphSummary.edgeCount} edge{graphSummary.edgeCount === 1 ? "" : "s"}</span>
                <span className="pill">{graphSummary.selectedCount} selected</span>
              </div>
            )}
            {headerTab === "outputs" && (
              <div className="outputs-pills header-pills">
                <span className="pill">{outputsSummary.images} image{outputsSummary.images === 1 ? "" : "s"}</span>
                <span className="pill">{outputsSummary.streams} stream{outputsSummary.streams === 1 ? "" : "s"}</span>
                <span className="pill">{outputsSummary.values} value{outputsSummary.values === 1 ? "" : "s"}</span>
              </div>
            )}
            {headerTab === "graph-editor" && isRunning && (
              <div className="header-stats">
                <span className="stat-badge running">
                  <span className="pulse-dot" />
                  {Math.round(progress * 100)}%
                </span>
              </div>
            )}
          </div>
          {headerTab === "graph-editor" && (
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
                <rect x="6" y="6" width="12" height="12" rx="1.5" />
              </svg>
            </button>
            <button
              className="icon-btn clear-cache-btn"
              onClick={handleClearBackendCache}
              disabled={isRunning}
              title="Clear Backend Cache"
            >
              <svg width="16" height="16" viewBox="0 0 48 48" fill="none">
                <g transform="translate(4 4) scale(0.8333)">
                  <path d="M44.7818 24.1702L31.918 7.09938L14.1348 20.5L27.5 37L30.8556 34.6644L44.7818 24.1702Z" fill="currentColor" stroke="currentColor" strokeWidth="4.30201" strokeLinejoin="round" />
                  <path d="M27.4998 37L23.6613 40.0748L13.0978 40.074L10.4973 36.6231L4.06543 28.0876L14.4998 20.2248" stroke="currentColor" strokeWidth="4.30201" strokeLinejoin="round" />
                  <path d="M13.2056 40.0721L44.5653 40.072" stroke="currentColor" strokeWidth="4.5" strokeLinecap="round" />
                </g>
              </svg>
            </button>
              {error && <span className="error-indicator" title={error}>!</span>}
            </div>
          )}
        </header>

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
                          hoveredPort={hoveredPort}
                          onOutputHover={(info) => setHoveredPort(info)}
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
          </>
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
          nodeTypes={smartConnectNodeTypes}
          sourceHandleType={smartConnectMenu.source?.type}
        />
      </div>
      </ReactFlowProvider>
    </PopupProvider>
  );
};

export default App;
