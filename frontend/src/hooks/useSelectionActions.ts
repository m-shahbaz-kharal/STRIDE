import { useCallback, useState } from "react";
import { Node, Edge } from "reactflow";
import { BlueprintNodeData, NodeTypeDefinition } from "../types";

interface UseSelectionActionsOptions {
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<BlueprintNodeData>[] | ((nds: Node<BlueprintNodeData>[]) => Node<BlueprintNodeData>[])) => void;
  setEdges: (edges: Edge[] | ((eds: Edge[]) => Edge[])) => void;
  selectedNodeIds: string[];
  setSelectedNodeIds: (ids: string[]) => void;
  selectedEdgeIds: string[];
  setSelectedEdgeIds: (ids: string[]) => void;
  setSelectedNodeId: (id: string | null) => void;
  takeSnapshot: () => void;
  createNodeFromType: (
    nodeType: NodeTypeDefinition,
    position: { x: number; y: number },
    handlers?: any
  ) => Node<BlueprintNodeData>;
  nodeHandlers: any;
}

export const useSelectionActions = ({
  nodes,
  edges,
  setNodes,
  setEdges,
  selectedNodeIds,
  setSelectedNodeIds,
  selectedEdgeIds,
  setSelectedEdgeIds,
  setSelectedNodeId,
  takeSnapshot,
  createNodeFromType,
  nodeHandlers,
}: UseSelectionActionsOptions) => {
  const [clipboard, setClipboard] = useState<Node<BlueprintNodeData>[] | null>(null);

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
  }, [selectedNodeIds, selectedEdgeIds, setNodes, setEdges, takeSnapshot, setSelectedNodeIds, setSelectedEdgeIds, setSelectedNodeId]);

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
  }, [selectedNodeIds, nodes, edges, createNodeFromType, nodeHandlers, setNodes, setEdges, takeSnapshot, setSelectedNodeIds, setSelectedNodeId, setSelectedEdgeIds]);

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
  }, [clipboard, createNodeFromType, nodeHandlers, setNodes, takeSnapshot, setSelectedNodeIds, setSelectedNodeId]);

  const handleSelectAll = useCallback(() => {
    const allNodeIds = nodes.map((n) => n.id);
    const allEdgeIds = edges.map((e) => e.id);
    setSelectedNodeIds(allNodeIds);
    setSelectedEdgeIds(allEdgeIds);
    setSelectedNodeId(allNodeIds[0] ?? null);
    setNodes((nds) => nds.map((node) => ({ ...node, selected: true })));
    setEdges((eds) => eds.map((edge) => ({ ...edge, selected: true })));
  }, [nodes, edges, setNodes, setEdges, setSelectedNodeIds, setSelectedEdgeIds, setSelectedNodeId]);

  return {
    clipboard,
    setClipboard,
    handleDeleteSelected,
    handleDuplicateSelected,
    handleCopy,
    handlePaste,
    handleSelectAll,
  };
};
