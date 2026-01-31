import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Node, Edge } from "reactflow";
import {
  AuthSession,
  GraphData,
  GraphRecord,
  createGraph,
  deleteGraph,
  listGraphs,
  updateGraph,
} from "../api";
import { BlueprintNodeData, NodeTypeDefinition, DashboardLayout } from "../types";
import { computeNodeDimensions } from "../graph/utils";

interface UseGraphCrudOptions {
  session: AuthSession | null;
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<BlueprintNodeData>[] | ((nds: Node<BlueprintNodeData>[]) => Node<BlueprintNodeData>[])) => void;
  setEdges: (edges: Edge[] | ((eds: Edge[]) => Edge[])) => void;
  setSelectedNodeIds: (ids: string[]) => void;
  setSelectedEdgeIds: (ids: string[]) => void;
  setSelectedNodeId: (id: string | null) => void;
  setHighlightedNodeIds: (ids: string[]) => void;
  setHeaderTab: (tab: "home" | "graph-editor" | "dashboard") => void;
  nodeLibrary: NodeTypeDefinition[];
  nodeIdRef: React.MutableRefObject<number>;
  buildDefaultInputValues: (nodeType: NodeTypeDefinition) => Record<string, any>;
  getInitialPorts: (nodeType: NodeTypeDefinition) => { input_ports: string[]; input_port_types: Record<string, any> };
  leftPanelCollapsed: boolean;
  rightPanelCollapsed: boolean;
  leftPanelWidth: number;
  rightPanelWidth: number;
  setLeftPanelCollapsed: (collapsed: boolean) => void;
  setRightPanelCollapsed: (collapsed: boolean) => void;
  setLeftPanelWidth: (width: number) => void;
  setRightPanelWidth: (width: number) => void;
  dashboardLayout: DashboardLayout;
  setDashboardLayout: (layout: DashboardLayout) => void;
  onSignOut: () => void;
}

export const useGraphCrud = ({
  session,
  nodes,
  edges,
  setNodes,
  setEdges,
  setSelectedNodeIds,
  setSelectedEdgeIds,
  setSelectedNodeId,
  setHighlightedNodeIds,
  setHeaderTab,
  nodeLibrary,
  nodeIdRef,
  buildDefaultInputValues,
  getInitialPorts,
  leftPanelCollapsed,
  rightPanelCollapsed,
  leftPanelWidth,
  rightPanelWidth,
  setLeftPanelCollapsed,
  setRightPanelCollapsed,
  setLeftPanelWidth,
  setRightPanelWidth,
  dashboardLayout,
  setDashboardLayout,
  onSignOut,
}: UseGraphCrudOptions) => {
  const [graphs, setGraphs] = useState<GraphRecord[]>([]);
  const [graphsLoading, setGraphsLoading] = useState(false);
  const [currentGraphId, setCurrentGraphId] = useState<string | null>(null);
  const [isGraphDirty, setIsGraphDirty] = useState(false);
  const [isDashboardDirty, setIsDashboardDirty] = useState(false);

  const lastSavedSnapshotRef = useRef<string | null>(null);
  const skipDirtyRef = useRef(false);
  const handlersAppliedRef = useRef(false);
  const dirtyCacheNodesRef = useRef<Set<string>>(new Set());

  const currentGraph = useMemo(
    () => graphs.find((g) => g.id === currentGraphId) || null,
    [graphs, currentGraphId]
  );

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
    handlersAppliedRef.current = false;
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
      const data = { ...(edge.data ?? {}) } as { kind?: string };
      if (!data.kind && edge.sourceHandle && edge.targetHandle) {
        const types = portTypeByNode.get(edge.source);
        const targetTypes = portTypeByNode.get(edge.target);
        const sourceType = types?.output?.[edge.sourceHandle];
        const targetType = targetTypes?.input?.[edge.targetHandle];
        const sourceKind = typeof sourceType === "string" ? sourceType : sourceType?.kind;
        const targetKind = typeof targetType === "string" ? targetType : targetType?.kind;
        data.kind = (sourceKind === "control" || targetKind === "control") ? "control" : "data";
      }
      return {
        id: edge.id,
        source: edge.source,
        target: edge.target,
        sourceHandle: edge.sourceHandle,
        targetHandle: edge.targetHandle,
        type: edge.type ?? "default",
        data,
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
    setIsDashboardDirty(false);

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
  }, [buildDefaultInputValues, getInitialPorts, nodeIdRef, nodeLibrary, setEdges, setLeftPanelCollapsed, setLeftPanelWidth, setNodes, setRightPanelCollapsed, setRightPanelWidth, setSelectedNodeIds, setSelectedEdgeIds, setSelectedNodeId, setHighlightedNodeIds, setDashboardLayout]);

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
      onSignOut();
    } finally {
      setGraphsLoading(false);
    }
  }, [currentGraphId, onSignOut, session, setEdges, setNodes]);

  useEffect(() => {
    if (session) {
      refreshGraphs();
    }
  }, [refreshGraphs, session]);

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

  const handleSaveGraph = useCallback(async () => {
    if (!session || !currentGraphId) return;
    const payload = serializeGraph();
    const updated = await updateGraph(session, currentGraphId, { data: payload });
    setGraphs((prev) => prev.map((graph) => (graph.id === updated.id ? updated : graph)));
    lastSavedSnapshotRef.current = JSON.stringify(updated.data);
    setIsGraphDirty(false);
    setIsDashboardDirty(false);
  }, [currentGraphId, serializeGraph, session]);

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

  const handleRenameGraphFromList = useCallback(async (graphId: string, name: string, description: string) => {
    if (!session) return;
    const updated = await updateGraph(session, graphId, { name, description });
    setGraphs((prev) => prev.map((graph) => (graph.id === updated.id ? updated : graph)));
  }, [session]);

  // Dirty state tracking
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

  return {
    graphs,
    setGraphs,
    graphsLoading,
    currentGraphId,
    setCurrentGraphId,
    currentGraph,
    isGraphDirty,
    setIsGraphDirty,
    isDashboardDirty,
    setIsDashboardDirty,
    handleCreateGraph,
    selectGraph,
    handleSaveGraph,
    handleDeleteGraph,
    handleRenameGraphFromList,
    refreshGraphs,
    serializeGraph,
    hydrateGraph,
    lastSavedSnapshotRef,
    skipDirtyRef,
    handlersAppliedRef,
    dirtyCacheNodesRef,
  };
};
