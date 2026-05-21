import { useCallback, useState } from "react";
import { Edge, Node } from "reactflow";

interface HistoryState<NodeData = any> {
  nodes: Node<NodeData>[];
  edges: Edge[];
}

interface UseUndoRedoOptions<NodeData = any> {
  maxHistory?: number;
  nodes: Node<NodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<NodeData>[]) => void;
  setEdges: (edges: Edge[]) => void;
  // When provided, undo/redo are no-ops while the function returns
  // true. The mutable-getter shape lets the caller wire in state that
  // is declared *after* `useUndoRedo` (e.g. ``isRunning``) without
  // reordering the component. Stops the editor from yanking the graph
  // out from under a streaming execution.
  isLocked?: () => boolean;
}

// Strip non-serialisable / non-restorable fields from a node before
// storing it in history. Handler closures (onParamChange, onDelete, …)
// are re-attached on restore by the App component's `hydrateGraph`
// pipeline, so keeping them in every history entry is pure memory
// waste — a 30-node graph × 50 entries would otherwise pin ~1500
// closures and their captured scopes in memory.
const stripVolatileFields = <NodeData,>(node: Node<NodeData>): Node<NodeData> => {
  const data = node.data as Record<string, unknown> | undefined;
  if (!data || typeof data !== "object") return node;
  const stripped: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(data)) {
    if (typeof value === "function") continue; // handler closure
    stripped[key] = value;
  }
  return { ...node, data: stripped as NodeData };
};

const snapshot = <NodeData,>(
  nodes: Node<NodeData>[],
  edges: Edge[],
): HistoryState<NodeData> => ({
  nodes: nodes.map((n) => stripVolatileFields(n)),
  edges: edges.map((e) => ({ ...e })),
});

export const useUndoRedo = <NodeData = any>({
  maxHistory = 50,
  nodes,
  edges,
  setNodes,
  setEdges,
  isLocked,
}: UseUndoRedoOptions<NodeData>) => {
  const [past, setPast] = useState<HistoryState<NodeData>[]>([]);
  const [future, setFuture] = useState<HistoryState<NodeData>[]>([]);

  const checkLocked = useCallback(() => {
    return typeof isLocked === "function" ? Boolean(isLocked()) : false;
  }, [isLocked]);

  const takeSnapshot = useCallback(() => {
    setPast((prev) => {
      const newPast = [...prev, snapshot(nodes, edges)];
      if (newPast.length > maxHistory) {
        return newPast.slice(newPast.length - maxHistory);
      }
      return newPast;
    });
    setFuture([]);
  }, [nodes, edges, maxHistory]);

  const undo = useCallback(() => {
    if (checkLocked()) return;
    if (past.length === 0) return;

    const previousState = past[past.length - 1];
    const newPast = past.slice(0, past.length - 1);

    setPast(newPast);
    setFuture((prev) => [snapshot(nodes, edges), ...prev]);

    setNodes(previousState.nodes);
    setEdges(previousState.edges);
  }, [past, nodes, edges, setNodes, setEdges, checkLocked]);

  const redo = useCallback(() => {
    if (checkLocked()) return;
    if (future.length === 0) return;

    const nextState = future[0];
    const newFuture = future.slice(1);

    setFuture(newFuture);
    setPast((prev) => [...prev, snapshot(nodes, edges)]);

    setNodes(nextState.nodes);
    setEdges(nextState.edges);
  }, [future, nodes, edges, setNodes, setEdges, checkLocked]);

  const canUndo = past.length > 0;
  const canRedo = future.length > 0;

  return {
    undo,
    redo,
    takeSnapshot,
    canUndo,
    canRedo,
    past,
    future,
  };
};
