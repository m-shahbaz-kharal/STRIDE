import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ReactFlow, {
  addEdge,
  Background,
  BackgroundVariant,
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
import DashboardView from "./components/dashboard/DashboardView";
import NodeSearchPalette from "./components/editor/NodeSearchPalette";
import AppHeader from "./components/layout/AppHeader";
import ConnectionToast from "./components/ConnectionToast";
import SmartConnectLine from "./components/SmartConnectLine";
import { ChevronLeft, ChevronRight, CopyIcon, DeleteIcon } from "./components/Icons";
import { PopupProvider } from "./context/PopupContext";
import { ConnectionDragProvider, ConnectionDragInfo } from "./context/ConnectionDragContext";
import AuthScreen from "./components/AuthScreen";
import GraphLibrary from "./components/GraphLibrary";
import JsonEditor from "./components/JsonEditor";
import AppDialog from "./components/AppDialog";
import { useGraphExecution } from "./hooks/useGraphExecution";
import { useUndoRedo } from "./hooks/useUndoRedo";
import { useNodeLibrary } from "./hooks/useNodeLibrary";
import { useConverterIndex } from "./hooks/useConverterIndex";
import { usePanelResize } from "./hooks/usePanelResize";
import { useConnectionValidation } from "./hooks/useConnectionValidation";
import { useConnectionToast } from "./hooks/useConnectionToast";
import { useKeyboardShortcuts } from "./hooks/useKeyboardShortcuts";
import { useNodeOperations } from "./hooks/useNodeOperations";
import { useSmartConnect } from "./hooks/useSmartConnect";
// Modular hooks for incremental refactoring
// NOTE: These hooks are ready to use but require additional wiring.
// Enabling them reduces App.tsx by ~400 lines (useGraphCrud), ~150 lines (useSelectionActions),
// ~150 lines (useNodeExecutionSync), and ~100 lines (useEdgeSelection).
// import { useGraphCrud } from "./hooks/useGraphCrud";
// import { useSelectionActions } from "./hooks/useSelectionActions";
// import { useNodeExecutionSync } from "./hooks/useNodeExecutionSync";
// import { useEdgeSelection } from "./hooks/useEdgeSelection";
// Domain layer - pure functions for type compatibility and graph traversal
import {
  getDownstreamNodes as domainGetDownstreamNodes,
  getDependentNodes as domainGetDependentNodes,
} from "./domain";
import HomeView from "./components/views/HomeView";
import GraphEditorView from "./components/views/GraphEditorView";
import {
  BlueprintNodeData,
  NodeTypeDefinition,
  PublishedPortData,
  DashboardLayout,
} from "./types";
import { CloseIcon } from "./components/Icons";
import {
  MIN_NODE_WIDTH,
  bezierIntersectsRect,
  computeNodeDimensions,
  getPortTypeColor,
  APP_HEADER_HEIGHT,
  HEADER_HEIGHT,
  PORT_ROW_HEIGHT,
} from "./graph/utils";
import {
  AuthSession,
  GraphData,
  GraphRecord,
  createGraph,
  deleteGraph,
  listGraphs,
  readSession,
  updateGraph,
  writeSession,
} from "./api";

type RightPanelTab = "inspector" | "execution";

const App = () => {
  const [selectedNodeIds, setSelectedNodeIds] = useState<string[]>([]);
  const [selectedEdgeIds, setSelectedEdgeIds] = useState<string[]>([]);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [useStreaming] = useState(true);
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<string[]>([]);
  const [hoveredPort, setHoveredPort] = useState<{ nodeId: string; port: string; direction: "input" | "output" } | null>(null);
  const [runningNodeIds, setRunningNodeIds] = useState<Set<string>>(new Set());
  const [session, setSession] = useState<AuthSession | null>(() => readSession());
  const [graphs, setGraphs] = useState<GraphRecord[]>([]);
  const [graphsLoading, setGraphsLoading] = useState(false);
  const [currentGraphId, setCurrentGraphId] = useState<string | null>(null);
  const [isGraphDirty, setIsGraphDirty] = useState(false);
  const [isDashboardDirty, setIsDashboardDirty] = useState(false);
  const [dashboardLayout, setDashboardLayout] = useState<DashboardLayout>({ widgets: [], viewport: { x: 0, y: 0, w: 1920, h: 1080 } });
  const [unsavedDialog, setUnsavedDialog] = useState<null | { mode: "home" | "switch"; targetGraphId?: string }>(null);
  const [appDialog, setAppDialog] = useState<{
    variant: "alert" | "confirm" | "prompt";
    title: string;
    message?: string;
    defaultValue?: string;
    placeholder?: string;
    onConfirm: (value?: string) => void;
  } | null>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const lastSavedSnapshotRef = useRef<string | null>(null);
  const skipDirtyRef = useRef(false);

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
  const isControlConnectionRef = useRef(false);
  const hoveredControlNodeIdRef = useRef<string | null>(null);

  // Right panel tab state
  const [rightPanelTab, setRightPanelTab] = useState<RightPanelTab>("inspector");

  // Header tab state
  const [headerTab, setHeaderTab] = useState<"home" | "graph-editor" | "dashboard">("home");

  // Clipboard state for copy/paste (nodes only, no edges)
  const [clipboard, setClipboard] = useState<Node<BlueprintNodeData>[] | null>(null);

  // JSON editor view state
  const [jsonViewEnabled, setJsonViewEnabled] = useState(false);
  const [jsonEditorContent, setJsonEditorContent] = useState("");

  // Custom selection box tracking for edge intersection selection
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionBox, setSelectionBox] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [previewEdgeIds, setPreviewEdgeIds] = useState<string[]>([]);
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const panFrameRef = useRef<number | null>(null);
  const [snapToGrid, setSnapToGrid] = useState(true);

  const [nodes, setNodes, onNodesChange] = useNodesState<BlueprintNodeData>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // ========== Use extracted hooks ==========

  // Node library hook
  const { nodeLibrary } = useNodeLibrary();

  // Converter index — Phase 5 §4.7. Empty until the fetch completes,
  // then drives "insert converter" suggestions on invalid edges.
  const { index: converterIndex } = useConverterIndex();



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
    setLeftPanelCollapsed,
    setRightPanelCollapsed,
    setLeftPanelWidth,
    setRightPanelWidth,
  } = usePanelResize();

  // Undo/Redo hook
  const { undo, redo, takeSnapshot, canUndo, canRedo } = useUndoRedo({
    nodes,
    edges,
    setNodes,
    setEdges,
  });

  // Node operations hook
  const {
    nodeIdRef,
    createNodeFromType,
    updateNodeData,
    handleParamChange,
    handleInputValueChange,
    handleAddInputPort,
    handleDeleteNode,
    clearAllCache,
    getPortYOffset,
    buildDefaultInputValues,
    getInitialPorts,
    handleTogglePublish,
  } = useNodeOperations({
    setNodes,
    setEdges,
    takeSnapshot,
    dashboardLayout,
    setDashboardLayout,
    onShowWarning: (message, onConfirm) => {
      setAppDialog({
        variant: "confirm",
        title: "Dependency Warning",
        message,
        onConfirm: () => {
          onConfirm();
          setAppDialog(null);
        }
      });
    },
    nodes,
  });

  // Connection validation hook
  const {
    nodeMap,
    arePortTypesCompatible,
    classifyPortForDrag,
    revalidateEdges,
    getPortTypeForHandle,
    getHandleRole,
    normalizeConnection,
    validateConnection,
    findConverter,
  } = useConnectionValidation({
    nodes,
    connectStartParams,
    converterIndex,
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
    isInterrupting,
    hasRunningNodes,
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
    stop,
  } = useGraphExecution();

  const nodeTypes = useMemo(() => ({ blueprint: BlueprintNode }), []);
  const edgeTypes = useMemo(() => ({ default: CustomEdge }), []);

  // PERF: Use refs for values that change frequently to keep nodeHandlers stable
  const executionIdRef = useRef(executionId);
  useEffect(() => { executionIdRef.current = executionId; }, [executionId]);
  const nodeMapRef = useRef(nodeMap);
  useEffect(() => { nodeMapRef.current = nodeMap; }, [nodeMap]);
  const handleRunGraphRef = useRef<(
    mode: "full" | "selection" | "from_node",
    targetNodes?: string[],
    extras?: { max_steps?: number; force_no_cache_nodes?: string[]; invalidate_cache_nodes?: string[] }
  ) => void>();
  const dirtyCacheNodesRef = useRef<Set<string>>(new Set());

  const clearBackendCacheForNodes = useCallback(async (nodeIds: Iterable<string>) => {
    const uniqueIds = Array.from(new Set(nodeIds));
    if (uniqueIds.length === 0) return;
    try {
      await fetch("/api/cache/clear-nodes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ node_ids: uniqueIds }),
      });
    } catch (e) {
      console.error("Failed to clear backend cache for nodes:", e);
    }
  }, []);

  // Helper to get all dependent nodes (upstream dependencies)
  // Uses domain layer function for the core traversal logic
  const getDependentNodes = useCallback((targetNodeIds: string[], includeCached = false): Set<string> => {
    const hasCachedOutput = (nodeId: string) => {
      const node = nodes.find((n) => n.id === nodeId);
      return Boolean(node?.data.last_outputs);
    };

    return domainGetDependentNodes(targetNodeIds, edges, {
      includeCached,
      hasCachedOutput,
      getPortType: getPortTypeForHandle,
    });
  }, [edges, getPortTypeForHandle, nodes]);

  // Uses domain layer function for downstream traversal
  const getDownstreamNodes = useCallback((startNodeIds: string[]): Set<string> => {
    return domainGetDownstreamNodes(startNodeIds, edges);
  }, [edges]);

  const clearNodesCacheUI = useCallback((nodeIds: Set<string>) => {
    if (nodeIds.size === 0) return;
    setNodes((existing) =>
      existing.map((node) =>
        nodeIds.has(node.id)
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

  const markCacheDirtyForNodes = useCallback((nodeIds: Set<string>) => {
    if (nodeIds.size === 0) return;
    nodeIds.forEach((nodeId) => dirtyCacheNodesRef.current.add(nodeId));
    clearNodesCacheUI(nodeIds);
  }, [clearNodesCacheUI]);

  const markNodeAndDownstreamDirty = useCallback((nodeId: string) => {
    const downstream = getDownstreamNodes([nodeId]);
    markCacheDirtyForNodes(downstream);
  }, [getDownstreamNodes, markCacheDirtyForNodes]);

  const handleParamChangeWithCache = useCallback(
    (nodeId: string, param: string, value: string | number | boolean | null) => {
      handleParamChange(nodeId, param, value);
      markNodeAndDownstreamDirty(nodeId);
    },
    [handleParamChange, markNodeAndDownstreamDirty]
  );

  const handleInputValueChangeWithCache = useCallback(
    (nodeId: string, port: string, value: string | number | boolean | null) => {
      handleInputValueChange(nodeId, port, value);
      markNodeAndDownstreamDirty(nodeId);
    },
    [handleInputValueChange, markNodeAndDownstreamDirty]
  );

  const handleAddInputPortWithCache = useCallback(
    (nodeId: string) => {
      handleAddInputPort(nodeId);
      markNodeAndDownstreamDirty(nodeId);
    },
    [handleAddInputPort, markNodeAndDownstreamDirty]
  );

  // Create handlers object for node data - keep stable to avoid re-renders
  // PERF: Access changing values via refs to avoid recreating handlers
  const nodeHandlers = useMemo(() => ({
    onDelete: handleDeleteNode,
    onRunSelection: (nodeId: string) => {
      handleRunGraphRef.current?.("from_node", [nodeId]);
    },
    onClearCache: async (nodeId: string) => {
      const downstream = getDownstreamNodes([nodeId]);
      markCacheDirtyForNodes(downstream);
      await clearBackendCacheForNodes(downstream);
    },
    onInterrupt: async (nodeId: string) => {
      // PERF: Access executionId from ref to keep handler stable
      if (!executionIdRef.current) return;
      try {
        await fetch(`/api/executions/${executionIdRef.current}/cancel/${nodeId}`, { method: "POST" });
      } catch (e) {
        console.error("Failed to interrupt node:", e);
      }
    },
    onParamChange: handleParamChangeWithCache,
    onPortHover: setHoveredPort,
    onInputValueChange: handleInputValueChangeWithCache,
    onAddInputPort: handleAddInputPortWithCache,
    onToggleControlPorts: (nodeId: string) => {
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== nodeId) return n;
          if (n.data.nodeType.startsWith("core.control")) return n;
          return { ...n, data: { ...n.data, showControlPorts: !n.data.showControlPorts } };
        })
      );
    },
    onToggleCache: (nodeId: string) => {
      const node = nodeMapRef.current.get(nodeId);
      const wasEnabled = Boolean(node?.data.cacheEnabled);
      setNodes((nds) =>
        nds.map((n) => {
          if (n.id !== nodeId) return n;
          if (n.data.nodeType.startsWith("core.control")) return n;
          return { ...n, data: { ...n.data, cacheEnabled: !n.data.cacheEnabled } };
        })
      );
      if (wasEnabled) {
        void clearBackendCacheForNodes([nodeId]);
      }
    },
    onTogglePublish: handleTogglePublish,
    // Phase 3 §7.4 — clear the inline error badge for this node. The
    // badge re-appears if the next run produces a fresh node_error.
    onDismissError: (nodeId: string) => {
      setNodes((nds) =>
        nds.map((n) =>
          n.id === nodeId
            ? { ...n, data: { ...n.data, errorDismissed: true } }
            : n
        )
      );
    },
    // PERF: Removed executionId and nodeMap from deps - accessed via refs now
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }), [
    clearBackendCacheForNodes,
    getDownstreamNodes,
    handleAddInputPortWithCache,
    handleDeleteNode,
    handleInputValueChangeWithCache,
    handleParamChangeWithCache,
    markCacheDirtyForNodes,
    setNodes,
    handleTogglePublish,
  ]);

  // ========== Computed values ==========



  // Collect published ports from all nodes
  const publishedItems = useMemo(() => {
    const items: { nodeId: string; nodeName: string; port: PublishedPortData }[] = [];

    for (const node of nodes) {
      const publishedPorts = node.data.published_ports || {};

      for (const [key, portData] of Object.entries(publishedPorts)) {
        items.push({
          nodeId: node.id,
          nodeName: node.data.displayName,
          port: portData,
        });
      }
    }

    return items;
  }, [nodes]);

  const handleJumpToNode = useCallback((nodeId: string) => {
    setHeaderTab("graph-editor");

    // Select the node
    setSelectedNodeIds([nodeId]);
    setSelectedNodeId(nodeId);

    // Center view on node
    const node = nodes.find(n => n.id === nodeId);
    if (node && reactFlowInstance) {
      const { x, y } = node.position;
      reactFlowInstance.setCenter(x + 100, y + 50, { zoom: 1, duration: 800 });
    }
  }, [nodes, reactFlowInstance]);

  const graphSummary = useMemo(() => ({
    nodeCount: nodes.length,
    edgeCount: edges.length,
    selectedCount: selectedNodeIds.length + selectedEdgeIds.length,
  }), [nodes.length, edges.length, selectedNodeIds.length, selectedEdgeIds.length]);

  const currentGraph = useMemo(
    () => graphs.find((graph) => graph.id === currentGraphId) ?? null,
    [graphs, currentGraphId]
  );

  const selectedNodes = useMemo(
    () => nodes.filter((node) => selectedNodeIds.includes(node.id)),
    [nodes, selectedNodeIds]
  );

  const smartConnectNodeTypes = useMemo(
    () => getCompatibleNodeTypes(nodeLibrary),
    [getCompatibleNodeTypes, nodeLibrary]
  );

  const minimapNodeColor = useCallback((node: Node<BlueprintNodeData>) => {
    const status = nodeStatuses.get(node.id);
    if (status === "running") return "#58a6ff";
    if (status === "completed") return "#3fb950";
    if (status === "error") return "#f85149";
    const category = node.data?.nodeType?.split(".")[1] ?? "";
    switch (category) {
      case "math":
        return "#d29922";
      case "control":
        return "#a371f7";
      case "container":
        return "#4a9eff";
      default:
        return "#8b949e";
    }
  }, [nodeStatuses]);

  const minimapNodeStroke = useCallback((node: Node<BlueprintNodeData>) => {
    if (node.selected) return "#f0c000";
    return "rgba(255,255,255,0.15)";
  }, []);

  const serializeGraph = useCallback((): GraphData => {
    const safeNodes = nodes.map((node) => ({
      id: node.id,
      type: node.type,
      position: node.position,
      width: node.width,
      height: node.height,
      data: {
        displayName: node.data.displayName,
        nodeType: node.data.nodeType,
        description: node.data.description,
        input_ports: node.data.input_ports,
        output_ports: node.data.output_ports,
        input_port_types: node.data.input_port_types,
        output_port_types: node.data.output_port_types,
        params: node.data.params,
        inputValues: node.data.inputValues,
        cacheEnabled: node.data.cacheEnabled,
        published_ports: node.data.published_ports,
      },
    }));

    const safeEdges = edges.map((edge) => ({
      id: edge.id,
      source: edge.source,
      target: edge.target,
      sourceHandle: edge.sourceHandle,
      targetHandle: edge.targetHandle,
      type: edge.type,
      data: edge.data,
    }));

    return {
      nodes: safeNodes,
      edges: safeEdges,
      ui: {
        leftPanelCollapsed,
        rightPanelCollapsed,
        leftPanelWidth,
        rightPanelWidth,
      },
      dashboard: dashboardLayout,
    };
  }, [dashboardLayout, edges, leftPanelCollapsed, leftPanelWidth, nodes, rightPanelCollapsed, rightPanelWidth]);

  const hydrateGraph = useCallback((data: GraphData) => {
    skipDirtyRef.current = true;
    handlersAppliedRef.current = false;  // Reset so handlers get applied to new nodes
    dirtyCacheNodesRef.current.clear();
    const typeMap = new Map(nodeLibrary.map((nodeType) => [nodeType.node_type, nodeType]));
    const hydratedNodes = data.nodes.map((node: any) => {
      const nodeType = typeMap.get(node.data?.nodeType);
      const defaultPorts = nodeType ? getInitialPorts(nodeType) : { input_ports: [], input_port_types: {} };
      const defaultInputValues = nodeType ? buildDefaultInputValues(nodeType) : {};
      const resolvedInputPorts = node.data?.input_ports ?? nodeType?.input_ports ?? defaultPorts.input_ports ?? [];
      const resolvedOutputPorts = node.data?.output_ports ?? nodeType?.output_ports ?? [];
      const resolvedParams = node.data?.params ?? {};
      const resolvedInputValues = node.data?.inputValues ?? defaultInputValues;
      const resolvedInputPortTypes = node.data?.input_port_types ?? nodeType?.input_port_types ?? defaultPorts.input_port_types ?? {};
      const resolvedOutputPortTypes = node.data?.output_port_types ?? nodeType?.output_port_types ?? {};

      const paramCount = Object.keys(nodeType?.params_schema ?? {}).length;
      const maxPorts = Math.max(resolvedInputPorts.length, resolvedOutputPorts.length);
      const fallbackSize = computeNodeDimensions(maxPorts, { paramCount });

      return {
        id: node.id,
        type: "blueprint",
        position: node.position ?? { x: 100, y: 100 },
        width: node.width ?? fallbackSize.width,
        height: node.height ?? fallbackSize.height,
        data: {
          displayName: nodeType?.display_name ?? node.data?.displayName ?? "Node",
          nodeType: nodeType?.node_type ?? node.data?.nodeType ?? "unknown",
          description: nodeType?.description ?? node.data?.description ?? "",
          input_ports: resolvedInputPorts,
          output_ports: resolvedOutputPorts,
          input_port_types: resolvedInputPortTypes,
          output_port_types: resolvedOutputPortTypes,
          params: resolvedParams,
          inputValues: resolvedInputValues,
          breakpoint: node.data?.breakpoint ?? false,
          metadata: nodeType,
          width: node.width ?? fallbackSize.width,
          height: node.height ?? fallbackSize.height,
          showControlPorts: node.data?.showControlPorts ?? false,
          cacheEnabled: node.data?.cacheEnabled ?? false,
          published_ports: node.data?.published_ports,
          executionLogs: [],
        },
      };
    });

    const portTypeByNode = new Map(
      hydratedNodes.map((node) => [
        node.id,
        {
          input: node.data.input_port_types ?? {},
          output: node.data.output_port_types ?? {},
        },
      ])
    );

    const hydratedEdges = data.edges.map((edge: any) => {
      const edgeData = { ...(edge.data ?? {}) } as {
        kind?: string;
        typeTooltip?: string;
        dashStyle?: "compatible" | "convertible" | "any-bridge";
      };
      const types = portTypeByNode.get(edge.source);
      const targetTypes = portTypeByNode.get(edge.target);
      const sourceType = edge.sourceHandle ? types?.output?.[edge.sourceHandle] : undefined;
      const targetType = edge.targetHandle ? targetTypes?.input?.[edge.targetHandle] : undefined;
      const sourceKind = typeof sourceType === "string" ? sourceType : sourceType?.kind;
      const targetKind = typeof targetType === "string" ? targetType : targetType?.kind;
      if (!edgeData.kind && sourceKind && targetKind) {
        edgeData.kind = (sourceKind === "control" || targetKind === "control") ? "control" : "data";
      }
      // Phase 3 §7.5/§7.6 — backfill type tooltip + dash style for
      // edges loaded from saved graphs so hover info works without a
      // re-connect.
      if (sourceType && targetType) {
        const fmt = (t: any) => {
          const base = (typeof t === "string" ? t : t.kind) || "any";
          const subtype = typeof t === "object" ? t.metadata?.subtype : undefined;
          return subtype ? `${base}[${subtype}]` : base;
        };
        if (!edgeData.typeTooltip) {
          edgeData.typeTooltip = `${fmt(sourceType)} → ${fmt(targetType)}`;
        }
        if (!edgeData.dashStyle) {
          const isControl = sourceKind === "control" || targetKind === "control";
          const isAnyBridge = !isControl
            && (sourceKind === "any" || targetKind === "any")
            && sourceKind !== targetKind;
          edgeData.dashStyle = isAnyBridge ? "any-bridge" : "compatible";
        }
      }
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: edge.type ?? "default",
        data: edgeData,
      };
    });

    const maxId = hydratedNodes.reduce((acc, node) => {
      const match = typeof node.id === "string" ? node.id.match(/node-(\d+)/) : null;
      if (!match) return acc;
      const value = Number(match[1]);
      return Number.isFinite(value) ? Math.max(acc, value) : acc;
    }, 0);
    if (nodeIdRef?.current != null) {
      nodeIdRef.current = Math.max(nodeIdRef.current, maxId + 1);
    }

    setNodes(hydratedNodes);
    setEdges(hydratedEdges);
    setSelectedNodeIds([]);
    setSelectedEdgeIds([]);
    setSelectedNodeId(null);
    setHighlightedNodeIds([]);
    setIsDashboardDirty(false); // Reset dashboard dirty state when loading a graph

    if (data.ui) {
      if (typeof data.ui.leftPanelCollapsed === "boolean") {
        setLeftPanelCollapsed(data.ui.leftPanelCollapsed);
      }
      if (typeof data.ui.rightPanelCollapsed === "boolean") {
        setRightPanelCollapsed(data.ui.rightPanelCollapsed);
      }
      if (typeof data.ui.leftPanelWidth === "number") {
        setLeftPanelWidth(data.ui.leftPanelWidth);
      }
      if (typeof data.ui.rightPanelWidth === "number") {
        setRightPanelWidth(data.ui.rightPanelWidth);
      }
    }

    if (data.dashboard) {
      setDashboardLayout(data.dashboard);
    } else {
      setDashboardLayout({ widgets: [], viewport: { x: 0, y: 0, w: 1920, h: 1080 } });
    }
  }, [buildDefaultInputValues, getInitialPorts, nodeIdRef, nodeLibrary, setEdges, setLeftPanelCollapsed, setLeftPanelWidth, setNodes, setRightPanelCollapsed, setRightPanelWidth]);

  // ========== Effects ==========

  const handleAuthSuccess = useCallback((nextSession: AuthSession) => {
    setSession(nextSession);
    writeSession(nextSession);
  }, []);

  const handleSignOut = useCallback(() => {
    setSession(null);
    writeSession(null);
    setGraphs([]);
    setCurrentGraphId(null);
    setNodes([]);
    setEdges([]);
    setDashboardLayout({ widgets: [], viewport: { x: 0, y: 0, w: 1920, h: 1080 } });
    setIsGraphDirty(false);
    setIsDashboardDirty(false);
    lastSavedSnapshotRef.current = null;
    setHeaderTab("home");
  }, [setEdges, setHeaderTab, setNodes]);

  const handleAccountSettings = useCallback(() => {
    setAppDialog({
      variant: "alert",
      title: "Coming Soon",
      message: "Account settings are coming soon.",
      onConfirm: () => setAppDialog(null),
    });
  }, []);

  const handleHeaderTabChange = useCallback((nextTab: "home" | "graph-editor" | "dashboard") => {
    if (nextTab === "home") {
      if (isGraphDirty || isDashboardDirty) {
        setUnsavedDialog({ mode: "home" });
        return;
      }
      setHeaderTab("home");
      return;
    }
    if (!currentGraphId) {
      setHeaderTab("home");
      return;
    }
    setHeaderTab(nextTab);
  }, [currentGraphId, isGraphDirty, isDashboardDirty, setHeaderTab]);

  const refreshGraphs = useCallback(async () => {
    if (!session) return;
    setGraphsLoading(true);
    try {
      const data = await listGraphs(session);
      setGraphs(data);
      if (currentGraphId && !data.find((graph) => graph.id === currentGraphId)) {
        setCurrentGraphId(null);
        setNodes([]);
        setEdges([]);
      }
    } catch (err) {
      handleSignOut();
    } finally {
      setGraphsLoading(false);
    }
  }, [currentGraphId, handleSignOut, session, setEdges, setNodes]);

  useEffect(() => {
    if (session) {
      refreshGraphs();
    }
  }, [refreshGraphs, session]);

  useEffect(() => {
    setNodes((currentNodes) =>
      currentNodes.map((node) => ({
        ...node,
        data: {
          ...node.data,
          ...nodeHandlers,
        },
      }))
    );
  }, [nodeHandlers, setNodes]);

  // Update node execution states when nodeStatuses change
  // PERF: Add early bailouts to avoid creating new objects when data hasn't changed
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
        const newOutputs = traceEntry?.outputs ?? node.data.last_outputs;
        const newLogs = traceEntry?.logs ?? node.data.executionLogs;
        const newDuration = traceEntry?.duration_ms;
        // Phase 3 §7.4 — surface structured error payload to the node.
        // Clear it when the node enters a non-error state (e.g. queued
        // for a fresh run); preserve user-dismissal otherwise.
        const newErrorPayload = traceEntry?.error_payload;
        const isError = status === "error";
        const isPreErrorTransition = status === "queued" || status === "running";
        const errorPayload = isPreErrorTransition
          ? undefined
          : (isError ? newErrorPayload : node.data.errorPayload);
        const errorDismissed = isPreErrorTransition ? false : node.data.errorDismissed;

        // PERF: Early bailout - skip if nothing actually changed for this node
        if (
          node.data.executionStatus === status &&
          node.data.executionDuration === newDuration &&
          node.data.last_outputs === newOutputs &&
          node.data.executionLogs === newLogs &&
          node.data.errorPayload === errorPayload &&
          node.data.errorDismissed === errorDismissed
        ) {
          return node;
        }

        return {
          ...node,
          data: {
            ...node.data,
            executionStatus: status,
            executionDuration: newDuration,
            last_outputs: newOutputs,
            executionLogs: newLogs,
            errorPayload,
            errorDismissed,
          },
        };
      })
    );
  }, [nodeStatuses, trace, isRunning, setNodes]);

  // PERF: Build a node lookup map for O(1) access instead of O(n) find() calls
  const nodeById = useMemo(() => {
    const map = new Map<string, typeof nodes[number]>();
    for (const node of nodes) map.set(node.id, node);
    return map;
  }, [nodes]);

  // Phase 3 §7.3 — re-validate every existing edge against the current
  // port-type maps. Edges that became invalid (e.g. because a Cast
  // node's `target_type` parameter changed) get `data.invalid = true`
  // and a reason string; CustomEdge renders a red `!` badge. The user
  // can fix or delete; we never auto-delete.
  //
  // Per Phase 3 spec: "full recompute is fine for now; debounced
  // incremental can come later." So we just rebuild on every nodes or
  // edges change; setEdges with bail-out keeps it cheap.
  const portTypeFingerprint = useMemo(() => {
    // Hash only the bits that affect validation so the effect doesn't
    // re-run on every position drag.
    return nodes.map((n) =>
      `${n.id}:${JSON.stringify(n.data.input_port_types || {})}|${JSON.stringify(n.data.output_port_types || {})}`
    ).join("\n");
  }, [nodes]);

  useEffect(() => {
    if (edges.length === 0) return;
    const invalidMap = revalidateEdges(edges as any);
    setEdges((existing) =>
      existing.map((edge) => {
        const entry = invalidMap.get(edge.id);
        const wasInvalid = (edge.data as any)?.invalid === true;
        if (entry) {
          if (
            wasInvalid &&
            (edge.data as any)?.invalidReason === entry.reason &&
            (edge.data as any)?.invalidClass === entry.classification
          ) {
            return edge;
          }
          return {
            ...edge,
            data: {
              ...(edge.data || {}),
              invalid: true,
              invalidReason: entry.reason,
              invalidClass: entry.classification,
            },
          };
        }
        if (wasInvalid) {
          const { invalid: _i, invalidReason: _r, invalidClass: _c, ...rest } = (edge.data || {}) as Record<string, unknown>;
          return { ...edge, data: rest };
        }
        return edge;
      })
    );
    // Intentionally depend only on the fingerprint, not `nodes`/`edges`
    // identity, so a position drag doesn't trigger this.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [portTypeFingerprint, revalidateEdges, setEdges]);

  // Update edges for running state
  // PERF: Build node lookup inside effect to avoid dependency on nodeById map identity
  useEffect(() => {
    // Build lookup inside effect - same O(n) but avoids Map identity change triggering effect
    const nodeByIdLocal = new Map<string, typeof nodes[number]>();
    for (const node of nodes) nodeByIdLocal.set(node.id, node);

    setEdges((existing) =>
      existing.map((edge) => {
        const sourceNode = nodeByIdLocal.get(edge.source);
        const sourceHasCachedOutput = Boolean(sourceNode?.data.last_outputs);
        const targetInRunningSet = runningNodeIds.has(edge.target);
        const shouldAnimate = isRunning && !isInterrupting && targetInRunningSet && !sourceHasCachedOutput;

        const sourceType = sourceNode?.data.nodeType ?? "";
        const isLoopNode = sourceType === "core.control.for" || sourceType === "core.control.while";
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
        const newStrokeWidth = (isRunning && targetInRunningSet) ? 2.5 : 2;

        // PERF: Early bailout - skip if this edge's styling wouldn't change
        const currentStyle = edge.style as React.CSSProperties | undefined;
        if (
          edge.animated === shouldAnimate &&
          currentStyle?.stroke === strokeColor &&
          currentStyle?.strokeWidth === newStrokeWidth &&
          currentStyle?.strokeDasharray === loopDash
        ) {
          return edge;
        }

        return {
          ...edge,
          animated: shouldAnimate,
          style: {
            ...edge.style,
            stroke: strokeColor,
            strokeWidth: newStrokeWidth,
            strokeDasharray: loopDash,
          },
        };
      })
    );
  }, [isRunning, isInterrupting, nodeStatuses, runningNodeIds, nodes, setEdges]);

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
  // PERF: Use Set for O(1) lookup and early bailout
  useEffect(() => {
    const previewSet = new Set(previewEdgeIds);
    setEdges((existing) =>
      existing.map((edge) => {
        const shouldPreview = previewSet.has(edge.id);
        // PERF: Early bailout if preview state hasn't changed
        if (edge.data?.isPreview === shouldPreview) return edge;
        return {
          ...edge,
          data: {
            ...edge.data,
            isPreview: shouldPreview,
          },
        };
      })
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

  // Handler propagation effect - applies nodeHandlers to nodes after hydration
  // When hydrateGraph loads nodes, it resets handlersAppliedRef to false so this effect re-runs
  // NOTE: nodes.length is included as dependency to trigger when nodes are loaded (hydrateGraph sets new nodes)
  const handlersAppliedRef = useRef(false);
  useEffect(() => {
    if (handlersAppliedRef.current) return;
    if (nodes.length === 0) return; // Don't apply handlers to empty graph
    handlersAppliedRef.current = true;
    setNodes((existing) =>
      existing.map((node) => {
        // Only update if handlers are actually missing
        if (node.data.onDelete === nodeHandlers.onDelete) return node;
        return {
          ...node,
          data: {
            ...node.data,
            ...nodeHandlers,
          },
        };
      })
    );
  }, [nodeHandlers, setNodes, nodes.length]);

  useEffect(() => {
    if (selectedNodeId && !nodes.some((node) => node.id === selectedNodeId)) {
      setSelectedNodeId(null);
    }
  }, [nodes, selectedNodeId]);

  const currentSnapshot = useMemo(() => {
    if (!currentGraphId) return null;
    return JSON.stringify(serializeGraph());
  }, [currentGraphId, serializeGraph]);

  useEffect(() => {
    if (!currentGraphId || !currentSnapshot) {
      setIsGraphDirty(false);
      return;
    }
    if (!lastSavedSnapshotRef.current) {
      setIsGraphDirty(true);
      return;
    }
    if (skipDirtyRef.current) {
      skipDirtyRef.current = false;
      lastSavedSnapshotRef.current = currentSnapshot;
      setIsGraphDirty(false);
      return;
    }
    setIsGraphDirty(currentSnapshot !== lastSavedSnapshotRef.current);
  }, [currentGraphId, currentSnapshot]);

  // ========== Graph operations ==========

  const handleCreateGraph = useCallback(async (name: string, description: string) => {
    if (!session) return;
    const payload: GraphData = { nodes: [], edges: [], ui: { leftPanelCollapsed, rightPanelCollapsed, leftPanelWidth, rightPanelWidth } };
    const created = await createGraph(session, { name, description, data: payload });
    setGraphs((prev) => [created, ...prev]);
    setCurrentGraphId(created.id);
    hydrateGraph(created.data);
    lastSavedSnapshotRef.current = JSON.stringify(created.data);
    setIsGraphDirty(false);
    setIsDashboardDirty(false);
    setHeaderTab("graph-editor");
  }, [hydrateGraph, leftPanelCollapsed, leftPanelWidth, rightPanelCollapsed, rightPanelWidth, session, setHeaderTab]);

  const selectGraph = useCallback((graphId: string) => {
    const graph = graphs.find((item) => item.id === graphId);
    if (!graph) return;
    setCurrentGraphId(graph.id);
    hydrateGraph(graph.data);
    lastSavedSnapshotRef.current = JSON.stringify(graph.data);
    setIsGraphDirty(false);
    setHeaderTab("graph-editor");
  }, [graphs, hydrateGraph, setHeaderTab]);

  const handleSelectGraph = useCallback((graphId: string) => {
    if (isGraphDirty) {
      setUnsavedDialog({ mode: "switch", targetGraphId: graphId });
      return;
    }
    selectGraph(graphId);
  }, [isGraphDirty, selectGraph]);

  const applyUnsavedAction = useCallback(() => {
    if (!unsavedDialog) return;
    if (unsavedDialog.mode === "home") {
      setHeaderTab("home");
    }
    if (unsavedDialog.mode === "switch" && unsavedDialog.targetGraphId) {
      selectGraph(unsavedDialog.targetGraphId);
    }
    setUnsavedDialog(null);
  }, [selectGraph, unsavedDialog]);

  const handleUnsavedContinue = useCallback(() => {
    applyUnsavedAction();
  }, [applyUnsavedAction]);

  const handleUnsavedCancel = useCallback(() => {
    setUnsavedDialog(null);
  }, []);

  const handleSaveGraph = useCallback(async () => {
    if (!session || !currentGraphId) return;
    const payload = serializeGraph();
    const updated = await updateGraph(session, currentGraphId, { data: payload });
    setGraphs((prev) => prev.map((graph) => (graph.id === updated.id ? updated : graph)));
    lastSavedSnapshotRef.current = JSON.stringify(updated.data);
    setIsGraphDirty(false);
    setIsDashboardDirty(false); // Also clear dashboard dirty state when saving
  }, [currentGraphId, serializeGraph, session]);

  const handleUnsavedSaveContinue = useCallback(async () => {
    if (!currentGraphId) return;
    await handleSaveGraph();
    applyUnsavedAction();
  }, [applyUnsavedAction, currentGraphId, handleSaveGraph]);

  const handleRenameGraph = useCallback(() => {
    if (!session || !currentGraphId) return;
    setAppDialog({
      variant: "prompt",
      title: "Rename Graph",
      message: "Enter a new name for this graph:",
      defaultValue: currentGraph?.name ?? "Untitled graph",
      placeholder: "Graph name",
      onConfirm: async (value) => {
        setAppDialog(null);
        if (!value?.trim()) return;
        const updated = await updateGraph(session, currentGraphId, { name: value.trim() });
        setGraphs((prev) => prev.map((g) => (g.id === updated.id ? updated : g)));
      },
    });
  }, [currentGraph?.name, currentGraphId, session]);

  const handleRenameGraphFromList = useCallback(async (graphId: string, name: string, description: string) => {
    if (!session) return;
    const updated = await updateGraph(session, graphId, { name, description });
    setGraphs((prev) => prev.map((graph) => (graph.id === updated.id ? updated : graph)));
  }, [session]);

  const handleDeleteGraph = useCallback(async (graphId: string) => {
    if (!session) return;
    const graph = graphs.find((item) => item.id === graphId);
    if (!graph) return;
    await deleteGraph(session, graphId);
    setGraphs((prev) => prev.filter((item) => item.id !== graphId));
    if (currentGraphId === graphId) {
      setCurrentGraphId(null);
      setNodes([]);
      setEdges([]);
      setIsGraphDirty(false);
      setIsDashboardDirty(false);
      lastSavedSnapshotRef.current = null;
      setHeaderTab("home");
    }
  }, [currentGraphId, graphs, session, setEdges, setHeaderTab, setNodes]);

  const buildGraphPayload = useCallback(
    (
      mode: "full" | "selection" | "from_node",
      targetNodes?: string[],
      extras?: { max_steps?: number; force_no_cache_nodes?: string[]; invalidate_cache_nodes?: string[] }
    ) => {
      const nodePayload = nodes.map((node) => ({
        id: node.id,
        type: node.data.nodeType,
        params: node.data.params,
        input_values: node.data.inputValues ?? {},
        input_ports_override: node.data.input_ports,
        input_port_types_override: node.data.input_port_types,
        output_ports_override: node.data.output_ports,
        output_port_types_override: node.data.output_port_types,
        cache_enabled: Boolean(node.data.cacheEnabled),
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
      if (mode === "from_node" && targetNodes?.length) {
        options.entry_nodes = targetNodes;
      }
      if (extras?.max_steps != null) {
        options.max_steps = extras.max_steps;
      }
      if (extras?.force_no_cache_nodes?.length) {
        options.force_no_cache_nodes = extras.force_no_cache_nodes;
      }
      if (extras?.invalidate_cache_nodes?.length) {
        options.invalidate_cache_nodes = extras.invalidate_cache_nodes;
      }

      return {
        graph: { nodes: nodePayload, links: linkPayload },
        options,
      };
    },
    [edges, nodes, getPortTypeForHandle]
  );

  const handleRunGraph = useCallback(
    async (
      mode: "full" | "selection" | "from_node",
      targetNodes?: string[],
      extras?: { max_steps?: number }
    ) => {
      if (nodes.length === 0) return;

      const resolvedTargets = targetNodes || (mode !== "full" ? selectedNodeIds : undefined);
      const downstreamForRerun = mode === "from_node"
        ? getDownstreamNodes(resolvedTargets?.length ? resolvedTargets : selectedNodeIds)
        : null;

      const runNodes = mode === "full"
        ? new Set(nodes.map((n) => n.id))
        : mode === "from_node"
          ? getDependentNodes(
            Array.from(downstreamForRerun ?? getDownstreamNodes(resolvedTargets || selectedNodeIds)),
            true
          )
          : getDependentNodes(resolvedTargets || selectedNodeIds);

      setRunningNodeIds((prev) => {
        const merged = new Set(prev);
        runNodes.forEach((id) => merged.add(id));
        return merged;
      });

      const dirtyNodesInRun = new Set<string>();
      dirtyCacheNodesRef.current.forEach((nodeId) => {
        if (runNodes.has(nodeId)) {
          dirtyNodesInRun.add(nodeId);
        }
      });
      const forceNoCacheNodes = new Set<string>(dirtyNodesInRun);
      const invalidateCacheNodes = new Set<string>(dirtyNodesInRun);
      if (downstreamForRerun) {
        downstreamForRerun.forEach((nodeId) => forceNoCacheNodes.add(nodeId));
      }

      const payload = buildGraphPayload(
        mode,
        resolvedTargets || (mode === "selection" ? selectedNodeIds : undefined),
        {
          max_steps: extras?.max_steps,
          force_no_cache_nodes: Array.from(forceNoCacheNodes),
          invalidate_cache_nodes: Array.from(invalidateCacheNodes),
        }
      );

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

      dirtyNodesInRun.forEach((nodeId) => dirtyCacheNodesRef.current.delete(nodeId));

      if (useStreaming) {
        runGraph(payload, runIds);
      } else {
        runGraphSync(payload, runIds).catch(() => {
          // Error handled by hook
        });
      }
    },
    [buildGraphPayload, getDependentNodes, getDownstreamNodes, isRunning, nodes, runGraph, runGraphSync, selectedNodeIds, setNodes, useStreaming]
  );
  useEffect(() => {
    handleRunGraphRef.current = handleRunGraph;
  }, [handleRunGraph]);

  const handleInterruptAll = useCallback(async () => {
    await stop();
  }, [stop]);

  const handleClearBackendCache = useCallback(async () => {
    try {
      const response = await fetch("/api/cache/clear", { method: "POST" });
      if (response.ok) {
        const data = await response.json();
        console.log(`Cleared ${data.cleared} cached entries`);
        clearAllCache();
        dirtyCacheNodesRef.current.clear();
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
        selected: true,
      };
      if (!isDuplicateEdge(newEdge, existingEdges) && !isDuplicateEdge(newEdge, newEdges)) {
        newEdges.push(newEdge);
      }
    });

    // Deselect all existing nodes and append new selected nodes
    setNodes((current) => [
      ...current.map((n) => ({ ...n, selected: false })),
      ...newNodes.map((n) => ({ ...n, selected: true })),
    ]);

    if (newEdges.length > 0) {
      // Deselect all existing edges and append new selected edges
      setEdges((current) => [
        ...current.map((e) => ({ ...e, selected: false })),
        ...newEdges,
      ]);
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

  // Phase 3 §7.2 — open the NodeSearchPalette without a source so it
  // acts as a Ctrl+K command palette. Anchor at viewport centre.
  const handleOpenSearch = useCallback(() => {
    if (headerTab !== "graph-editor" || jsonViewEnabled) return;
    const screenPosition = {
      x: Math.floor(window.innerWidth / 2 - 170),
      y: Math.floor(window.innerHeight / 3),
    };
    const flowPosition = reactFlowInstance
      ? reactFlowInstance.screenToFlowPosition({
        x: screenPosition.x + 170,
        y: screenPosition.y + 60,
      })
      : { x: 0, y: 0 };
    openSmartConnect(screenPosition, flowPosition, null as any, undefined);
  }, [headerTab, jsonViewEnabled, openSmartConnect, reactFlowInstance]);

  useKeyboardShortcuts({
    onDelete: handleDeleteSelected,
    onSelectAll: handleSelectAll,
    onDuplicate: handleDuplicateSelected,
    onCopy: handleCopy,
    onPaste: handlePaste,
    onUndo: undo,
    onRedo: redo,
    onRunGraph: () => handleRunGraph("full"),
    onRunSelection: () => handleRunGraph("selection"),
    onInterruptAll: handleInterruptAll,
    onOpenSearch: handleOpenSearch,
    canDuplicate: selectedNodeIds.length > 0,
    canCopy: selectedNodeIds.length > 0,
    canRunGraph: nodes.length > 0 && !isRunning && !jsonViewEnabled,
    canRunSelection: selectedNodeIds.length > 0 && !isRunning && !jsonViewEnabled,
    canInterrupt: (isRunning || hasRunningNodes) && Boolean(executionId),
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

  // Phase 5 §4.7 — insert a converter node that bridges an invalid edge.
  //
  // Given a source/target pair and the converter spec the index returned,
  // this picks the converter's first input/output ports, places the new
  // node between the existing nodes, and wires source -> converter ->
  // target. Falls back gracefully if the spec has no ports or the
  // converter's node type isn't in the loaded library.
  const insertConverterBetween = useCallback(
    (
      converterNodeType: string,
      source: { nodeId: string; handleId: string },
      target: { nodeId: string; handleId: string },
    ): boolean => {
      const definition = nodeLibrary.find((n) => n.node_type === converterNodeType);
      if (!definition) return false;
      // Ignore control_in/out when picking the data port; the convention
      // is that the first non-control port is the value carrier.
      const inputs = (definition.input_ports || []).filter((p) => p !== "control_in");
      const outputs = (definition.output_ports || []).filter((p) => p !== "control_out");
      const inputPort = inputs[0];
      const outputPort = outputs[0];
      if (!inputPort || !outputPort) return false;

      const sourceNode = nodeMap.get(source.nodeId);
      const targetNode = nodeMap.get(target.nodeId);
      if (!sourceNode || !targetNode) return false;

      const midX = (sourceNode.position.x + targetNode.position.x) / 2;
      const midY = (sourceNode.position.y + targetNode.position.y) / 2;
      const newNode = createNodeFromType(definition, { x: midX, y: midY }, nodeHandlers);

      takeSnapshot();
      setNodes((existing) => existing.concat(newNode));
      const sourceType = getPortTypeForHandle(source.nodeId, source.handleId, "source");
      const targetType = getPortTypeForHandle(target.nodeId, target.handleId, "target");
      const upstreamColor = getPortTypeColor(sourceType);
      const downstreamColor = getPortTypeColor(targetType);

      setEdges((existing) => {
        // Drop any prior edge into the same target port; React Flow's
        // single-incoming convention keeps the graph deterministic.
        const filtered = existing.filter(
          (edge) => !(edge.target === target.nodeId && edge.targetHandle === target.handleId)
        );
        const upstream = addEdge(
          {
            source: source.nodeId,
            sourceHandle: source.handleId,
            target: newNode.id,
            targetHandle: inputPort,
            type: "default",
            animated: false,
            style: { stroke: upstreamColor, strokeWidth: 2 },
            data: { kind: "data" as const },
          },
          filtered,
        );
        return addEdge(
          {
            source: newNode.id,
            sourceHandle: outputPort,
            target: target.nodeId,
            targetHandle: target.handleId,
            type: "default",
            animated: false,
            style: { stroke: downstreamColor, strokeWidth: 2 },
            data: { kind: "data" as const },
          },
          upstream,
        );
      });
      return true;
    },
    [
      nodeLibrary,
      nodeMap,
      createNodeFromType,
      nodeHandlers,
      setNodes,
      setEdges,
      takeSnapshot,
      getPortTypeForHandle,
    ],
  );

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
        // Phase 5 §4.7: when the type system rejects but a converter
        // bridges the gap, offer a one-click "Insert <converter>" CTA.
        if (
          validation.classification === "convertible" &&
          validation.suggestedConverter &&
          normalized.source &&
          normalized.sourceHandle &&
          normalized.target &&
          normalized.targetHandle
        ) {
          const conv = validation.suggestedConverter;
          const sourceRef = {
            nodeId: normalized.source,
            handleId: normalized.sourceHandle,
          };
          const targetRef = {
            nodeId: normalized.target,
            handleId: normalized.targetHandle,
          };
          showConnectionMessage(
            `${validation.reason || "Type mismatch"} — insert ${conv.display_name}?`,
            {
              tone: "info",
              action: {
                label: `Insert ${conv.display_name}`,
                run: () => {
                  insertConverterBetween(conv.node_type, sourceRef, targetRef);
                },
              },
            },
          );
          return;
        }
        showConnectionMessage(validation.reason || "These connectors cannot be linked");
        return;
      }

      const sourceType = getPortTypeForHandle(normalized.source!, normalized.sourceHandle!, "source");
      const targetType = getPortTypeForHandle(normalized.target!, normalized.targetHandle!, "target");
      const isControlConnection = sourceType.kind === "control" || targetType.kind === "control";
      const edgeColor = getPortTypeColor(sourceType);
      // Phase 3 §7.5/§7.6 — derive hover tooltip + dash style from
      // the type registry. The tooltip exposes kind[subtype] on both
      // sides so the user can debug at a glance.
      const formatTypeWithSubtype = (t: typeof sourceType) => {
        const base = (t.kind || "any") as string;
        const subtype = t.metadata?.subtype as string | undefined;
        return subtype ? `${base}[${subtype}]` : base;
      };
      const typeTooltip = `${formatTypeWithSubtype(sourceType)} → ${formatTypeWithSubtype(targetType)}`;
      const isAnyBridge = !isControlConnection
        && (sourceType.kind === "any" || targetType.kind === "any")
        && sourceType.kind !== targetType.kind;
      const dashStyle: "compatible" | "convertible" | "any-bridge" =
        isAnyBridge ? "any-bridge" : "compatible";

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
            data: {
              kind: isControlConnection ? "control" : "data",
              typeTooltip,
              dashStyle,
            },
          },
          filtered
        );
      });
      if (isControlConnection) {
        setNodes((existing) =>
          existing.map((node) => {
            if (node.id !== normalized.source && node.id !== normalized.target) return node;
            if (node.data.nodeType.startsWith("core.control")) {
              return node.data.showControlPorts ? node : { ...node, data: { ...node.data, showControlPorts: true } };
            }
            return node.data.showControlPorts ? node : { ...node, data: { ...node.data, showControlPorts: true } };
          })
        );
      }
      setConnectionLineIsInvalid(false);
    },
    [
      edges,
      getPortTypeForHandle,
      insertConverterBetween,
      normalizeConnection,
      setEdges,
      setNodes,
      showConnectionMessage,
      takeSnapshot,
      validateConnection,
    ]
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
        isControlConnectionRef.current = type.kind === "control";
        setConnectionLineColor(getPortTypeColor(type));
        setConnectionLineIsInvalid(false);
      } else {
        isControlConnectionRef.current = false;
        setConnectionLineColor(undefined);
        setConnectionLineIsInvalid(false);
      }
    },
    [getPortTypeForHandle]
  );

  const clearHoveredControlPorts = useCallback(() => {
    const prev = hoveredControlNodeIdRef.current;
    if (!prev) return;
    hoveredControlNodeIdRef.current = null;
    setNodes((existing) =>
      existing.map((node) =>
        node.id === prev
          ? { ...node, data: { ...node.data, hoverControlPorts: undefined } }
          : node
      )
    );
  }, [setNodes]);

  const updateHoveredControlNode = useCallback((nodeId: string | null) => {
    const prev = hoveredControlNodeIdRef.current;
    if (prev === nodeId) return;
    hoveredControlNodeIdRef.current = nodeId;
    setNodes((existing) =>
      existing.map((node) => {
        if (node.id === prev) {
          return { ...node, data: { ...node.data, hoverControlPorts: undefined } };
        }
        if (nodeId && node.id === nodeId) {
          if (node.data.nodeType.startsWith("core.control")) return node;
          return { ...node, data: { ...node.data, hoverControlPorts: true } };
        }
        return node;
      })
    );
  }, [setNodes]);

  const onConnectEnd = useCallback(
    (event: MouseEvent | TouchEvent) => {
      if (connectSucceededRef.current) {
        connectSucceededRef.current = false;
        clearHoveredControlPorts();
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
      isControlConnectionRef.current = false;
      clearHoveredControlPorts();
      setConnectionLineColor(undefined);
      setConnectionLineIsInvalid(false);
    },
    [clearHoveredControlPorts, connectStartParams, reactFlowInstance, getPortTypeForHandle, openSmartConnect]
  );

  // ========== Smart connect select ==========

  const handleSmartConnectSelect = useCallback(
    (nodeType: NodeTypeDefinition) => {
      takeSnapshot();

      const { flowPosition, source } = smartConnectMenu;

      // Phase 3 §7.2 — Ctrl+K (no source) just creates the node at the
      // anchor flow position. No auto-wiring needed.
      if (!source) {
        const newNode = createNodeFromType(nodeType, flowPosition, nodeHandlers);
        setNodes((nds) => nds.concat(newNode));
        closeSmartConnect();
        return;
      }

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
      const isControlConnection =
        (typeof compatiblePort.sourceType === "object" && compatiblePort.sourceType?.kind === "control") ||
        (typeof compatiblePort.targetType === "object" && compatiblePort.targetType?.kind === "control");
      const hydratedNewNode = isControlConnection
        ? { ...newNode, data: { ...newNode.data, showControlPorts: true } }
        : newNode;

      setNodes((nds) => nds.concat(hydratedNewNode));

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
          // Phase 3 §7.5/§7.6 — same tooltip+dash logic as handleConnect.
          const formatTypeWithSubtype = (t: typeof sourceType) => {
            if (typeof t !== "object" || !t) return "any";
            const base = ((t as any).kind || "any") as string;
            const subtype = (t as any).metadata?.subtype as string | undefined;
            return subtype ? `${base}[${subtype}]` : base;
          };
          const sKind = typeof sourceType === "object" ? (sourceType as any).kind : sourceType;
          const tKind = typeof targetType === "object" ? (targetType as any).kind : targetType;
          const typeTooltip = `${formatTypeWithSubtype(sourceType as any)} → ${formatTypeWithSubtype(targetType as any)}`;
          const isAnyBridge = !isControlConnection
            && (sKind === "any" || tKind === "any")
            && sKind !== tKind;
          const dashStyle: "compatible" | "convertible" | "any-bridge" =
            isAnyBridge ? "any-bridge" : "compatible";
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
                data: {
                  kind: isControlConnection ? "control" : "data",
                  typeTooltip,
                  dashStyle,
                },
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
      return;
    }

    if (connectStartParams && reactFlowInstance && reactFlowWrapper.current) {
      if (panFrameRef.current !== null) {
        cancelAnimationFrame(panFrameRef.current);
      }
      panFrameRef.current = requestAnimationFrame(() => {
        panFrameRef.current = null;
        const rect = reactFlowWrapper.current?.getBoundingClientRect();
        if (!rect) return;
        const edge = 48;
        const speed = 10;
        let dx = 0;
        let dy = 0;
        if (e.clientX < rect.left + edge) dx = speed;
        if (e.clientX > rect.right - edge) dx = -speed;
        if (e.clientY < rect.top + edge) dy = speed;
        if (e.clientY > rect.bottom - edge) dy = -speed;
        if (dx === 0 && dy === 0) return;
        const viewport = reactFlowInstance.getViewport();
        reactFlowInstance.setViewport({
          x: viewport.x + dx,
          y: viewport.y + dy,
          zoom: viewport.zoom,
        }, { duration: 0 });
      });
    }

    if (connectStartParams && isControlConnectionRef.current) {
      const hoveredElement = document.elementFromPoint(e.clientX, e.clientY);
      const nodeEl = hoveredElement instanceof HTMLElement
        ? hoveredElement.closest(".react-flow__node")
        : null;
      const nodeId = nodeEl instanceof HTMLElement ? nodeEl.dataset.id ?? null : null;
      updateHoveredControlNode(nodeId);
    } else if (hoveredControlNodeIdRef.current) {
      clearHoveredControlPorts();
    }
  }, [clearHoveredControlPorts, connectStartParams, isSelecting, reactFlowInstance, selectionBox, updateHoveredControlNode, updatePreviewEdges]);

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

  // Phase 3 §7.1 — broadcast the active connection drag so every
  // BlueprintNode can decorate its ports without a `nodes` rebuild.
  // Must be declared above any early returns to keep the hook order stable
  // across the unauthenticated → authenticated transition.
  const connectionDragInfo: ConnectionDragInfo | null = useMemo(() => {
    if (!connectStartParams?.nodeId || !connectStartParams.handleId || !connectStartParams.handleType) {
      return null;
    }
    return {
      nodeId: connectStartParams.nodeId,
      handleId: connectStartParams.handleId,
      handleType: connectStartParams.handleType,
    };
  }, [connectStartParams]);

  // ========== Render ==========

  if (!session) {
    return <AuthScreen onAuthSuccess={handleAuthSuccess} />;
  }

  return (
    <PopupProvider>
      <ReactFlowProvider>
       <ConnectionDragProvider drag={connectionDragInfo} classifyPort={classifyPortForDrag}>
        <div className="app-shell">
          <HomeView
            graphs={graphs}
            currentGraphId={currentGraphId}
            isLoading={graphsLoading}
            onCreate={handleCreateGraph}
            onSelect={handleSelectGraph}
            onUpdate={handleRenameGraphFromList}
            onDelete={handleDeleteGraph}
            visible={headerTab === "home"}
          />
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
            {jsonViewEnabled ? (
              <JsonEditor
                graphJson={jsonEditorContent}
                onClose={() => setJsonViewEnabled(false)}
              />
            ) : (
              <>
                <ReactFlow
                  nodes={nodes}
                  edges={edges}
                  onNodesChange={onNodesChange}
                  onEdgesChange={onEdgesChange}
                  onInit={setReactFlowInstance}
                  onNodeMouseEnter={(_, node) => setHoveredNodeId(node.id)}
                  onNodeMouseLeave={() => setHoveredNodeId(null)}
                  onConnect={handleConnect}
                  onConnectStart={onConnectStart}
                  onConnectEnd={onConnectEnd}
                  onMoveStart={closeSmartConnect}
                  onNodeDragStart={() => takeSnapshot()}
                  onSelectionDragStart={() => takeSnapshot()}
                  onSelectionChange={handleSelectionChange}
                  nodeTypes={nodeTypes}
                  edgeTypes={edgeTypes}
                  fitView
                  minZoom={0.02}
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
                  snapToGrid={snapToGrid}
                  snapGrid={[20, 20]}
                >
                  {snapToGrid && <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.15)" />}
                  <Controls
                    showZoom
                    showFitView
                    showInteractive={false}
                    position="bottom-left"
                    style={{ left: actualLeftWidth }}
                  />
                  <MiniMap
                    nodeColor={minimapNodeColor}
                    nodeStrokeColor={minimapNodeStroke}
                    nodeStrokeWidth={1}
                    maskColor="rgba(0,0,0,0.65)"
                    style={{
                      backgroundColor: "rgba(20,25,35,0.9)",
                      right: actualRightWidth,
                    }}
                    pannable
                    zoomable
                  />
                </ReactFlow>
                {/* Graph Editor Controls (Undo/Redo & Snap) */}
                <div style={{ position: 'absolute', top: APP_HEADER_HEIGHT + 20, right: actualRightWidth + 20, zIndex: 5, display: 'flex', gap: '10px', transition: 'right 0.3s ease' }}>
                  {/* Undo/Redo */}
                  <div style={{
                    background: 'var(--bg-elevated)',
                    padding: '4px',
                    borderRadius: '8px',
                    display: 'flex',
                    gap: '4px',
                    boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                    border: '1px solid var(--border-subtle)',
                    alignItems: 'center',
                    height: '36px',
                    boxSizing: 'border-box'
                  }}>
                    <button
                      onClick={undo}
                      disabled={!canUndo}
                      title="Undo (Ctrl+Z)"
                      className="icon-btn"
                      style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: !canUndo ? 0.3 : 1 }}>
                        <path d="M3 7v6h6"></path>
                        <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"></path>
                      </svg>
                    </button>
                    <button
                      onClick={redo}
                      disabled={!canRedo}
                      title="Redo (Ctrl+Y)"
                      className="icon-btn"
                      style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                    >
                      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: !canRedo ? 0.3 : 1 }}>
                        <path d="M21 7v6h-6"></path>
                        <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13"></path>
                      </svg>
                    </button>
                  </div>

                  {/* Snap Button */}
                  <button
                    onClick={() => setSnapToGrid(!snapToGrid)}
                    title={`Snap to Grid: ${snapToGrid ? "On" : "Off"}`}
                    style={{
                      width: '36px',
                      height: '36px',
                      borderRadius: '8px',
                      border: '1px solid var(--border-subtle)',
                      background: snapToGrid ? 'var(--accent-primary)' : 'var(--bg-elevated)',
                      color: snapToGrid ? 'white' : 'var(--text-secondary)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      cursor: 'pointer',
                      boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                      transition: 'all 0.2s ease'
                    }}
                  >
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                      <path d="M10 10h4v4h-4zm0-6h4v4h-4zm0 12h4v4h-4zM4 4h4v4H4zm0 6h4v4H4zm0 6h4v4H4zM16 4h4v4h-4zm0 6h4v4h-4zm0 6h4v4h-4z" />
                    </svg>
                  </button>
                </div>
                <ConnectionToast message={connectionMessage} />
              </>
            )}
          </div>
          <div
            style={{
              display: headerTab === "dashboard" ? "block" : "none",
              position: "absolute",
              top: "44px",
              left: 0,
              right: 0,
              bottom: 0,
              background: "var(--bg-canvas)",
              overflow: "hidden",
              margin: 0,
              padding: 0,
              zIndex: 5
            }}
          >
            <DashboardView
              nodes={nodes}
              outputs={outputs}
              onRunGraph={handleRunGraphRef.current?.bind(null, "full")}
              isRunning={isRunning}
              onInputChange={handleInputValueChange}
              onSave={handleSaveGraph}
              publishedItems={publishedItems}
              onJumpToNode={handleJumpToNode}
              onTogglePublish={handleTogglePublish}
              onDirtyChange={setIsDashboardDirty}
              layout={dashboardLayout}
              onLayoutChange={(newLayout) => {
                setDashboardLayout(newLayout);
                setIsDashboardDirty(true);
              }}
            />
          </div>

          <AppHeader
            headerTab={headerTab}
            onTabChange={handleHeaderTabChange}
            graphSummary={graphSummary}

            graphName={currentGraph?.name ?? null}
            isGraphDirty={isGraphDirty || isDashboardDirty}
            isRunning={isRunning}
            isInterrupting={isInterrupting}
            isConnected={isConnected}
            progress={progress}
            error={error}
            executionId={executionId}
            nodesCount={nodes.length}
            jsonViewEnabled={jsonViewEnabled}
            onToggleJsonView={() => {
              if (!jsonViewEnabled) {
                setJsonEditorContent(JSON.stringify(serializeGraph(), null, 2));
              }
              setJsonViewEnabled((prev) => !prev);
            }}
            onRunGraph={() => handleRunGraph("full")}
            onInterruptAll={handleInterruptAll}
            onClearCache={handleClearBackendCache}
            onSaveGraph={handleSaveGraph}
            onRenameGraph={handleRenameGraph}
            onSignOut={handleSignOut}
            onAccountSettings={handleAccountSettings}
            hasRunningNodes={hasRunningNodes}
          />

          {unsavedDialog && (
            <div className="modal-overlay">
              <div className="modal-card">
                <div className="modal-header">
                  <h3>Unsaved changes</h3>
                  <button type="button" className="icon-btn" onClick={handleUnsavedCancel}>
                    <CloseIcon />
                  </button>
                </div>
                <div className="modal-body">
                  <p>You have unsaved changes. What would you like to do?</p>
                </div>
                <div className="modal-actions">
                  <button type="button" className="ghost-btn" onClick={handleUnsavedCancel}>
                    Stay
                  </button>
                  <button type="button" className="ghost-btn" onClick={handleUnsavedContinue}>
                    Continue without saving
                  </button>
                  <button type="button" className="primary-btn" onClick={handleUnsavedSaveContinue}>
                    Save and continue
                  </button>
                </div>
              </div>
            </div>
          )}

          {appDialog && (
            <AppDialog
              isOpen={true}
              variant={appDialog.variant}
              title={appDialog.title}
              message={appDialog.message}
              defaultValue={appDialog.defaultValue}
              placeholder={appDialog.placeholder}
              onConfirm={appDialog.onConfirm}
              onCancel={() => setAppDialog(null)}
            />
          )}

          {headerTab === "graph-editor" && !jsonViewEnabled && (
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
                            allNodes={nodes}
                            edges={edges}
                            hoveredNodeId={hoveredNodeId}
                            onParamChange={handleParamChange}
                            onInputValueChange={handleInputValueChange}
                            onJumpToNode={handleJumpToNode}
                            onDelete={handleDeleteNode}
                            onDuplicate={(nodeId) => {
                              setSelectedNodeIds([nodeId]);
                              setSelectedNodeId(nodeId);
                              setTimeout(() => handleDuplicateSelected(), 0);
                            }}
                            hoveredPort={hoveredPort}
                            onPortHover={(info) => setHoveredPort(info)}
                            onTogglePublish={handleTogglePublish}
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

          <NodeSearchPalette
            isOpen={smartConnectMenu.isOpen}
            position={smartConnectMenu.position}
            onClose={closeSmartConnect}
            onSelect={handleSmartConnectSelect}
            nodeTypes={smartConnectNodeTypes}
            source={smartConnectMenu.source ? {
              ...smartConnectMenu.source,
              portType: smartConnectMenu.source.nodeId && smartConnectMenu.source.handleId
                ? getPortTypeForHandle(
                  smartConnectMenu.source.nodeId,
                  smartConnectMenu.source.handleId,
                  smartConnectMenu.source.type
                )
                : undefined,
            } : null}
          />
        </div>
       </ConnectionDragProvider>
      </ReactFlowProvider>
    </PopupProvider>
  );
};

export default App;
