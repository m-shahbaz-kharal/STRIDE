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
}

export const useUndoRedo = <NodeData = any>({
  maxHistory = 50,
  nodes,
  edges,
  setNodes,
  setEdges,
}: UseUndoRedoOptions<NodeData>) => {
  const [past, setPast] = useState<HistoryState<NodeData>[]>([]);
  const [future, setFuture] = useState<HistoryState<NodeData>[]>([]);

  const takeSnapshot = useCallback(() => {
    setPast((prev) => {
      const newPast = [...prev, { nodes, edges }];
      if (newPast.length > maxHistory) {
        return newPast.slice(newPast.length - maxHistory);
      }
      return newPast;
    });
    setFuture([]);
  }, [nodes, edges, maxHistory]);

  const undo = useCallback(() => {
    if (past.length === 0) return;

    const previousState = past[past.length - 1];
    const newPast = past.slice(0, past.length - 1);

    setPast(newPast);
    setFuture((prev) => [{ nodes, edges }, ...prev]);

    setNodes(previousState.nodes);
    setEdges(previousState.edges);
  }, [past, nodes, edges, setNodes, setEdges]);

  const redo = useCallback(() => {
    if (future.length === 0) return;

    const nextState = future[0];
    const newFuture = future.slice(1);

    setFuture(newFuture);
    setPast((prev) => [...prev, { nodes, edges }]);

    setNodes(nextState.nodes);
    setEdges(nextState.edges);
  }, [future, nodes, edges, setNodes, setEdges]);

  const canUndo = past.length > 0;
  const canRedo = future.length > 0;

  return {
    undo,
    redo,
    takeSnapshot,
    canUndo,
    canRedo,
    past, 
    future
  };
};
