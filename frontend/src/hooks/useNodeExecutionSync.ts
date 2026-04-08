import { useEffect, useMemo, useRef } from "react";
import { Node, Edge } from "reactflow";
import { BlueprintNodeData } from "../types";

interface UseNodeExecutionSyncOptions {
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  setNodes: (nodes: Node<BlueprintNodeData>[] | ((nds: Node<BlueprintNodeData>[]) => Node<BlueprintNodeData>[])) => void;
  setEdges: (edges: Edge[] | ((eds: Edge[]) => Edge[])) => void;
  nodeStatuses: Map<string, string>;
  trace: Array<{
    node_id: string;
    outputs?: Record<string, any>;
    logs?: string[];
    duration_ms?: number;
  }>;
  isRunning: boolean;
  isInterrupting: boolean;
  runningNodeIds: Set<string>;
  setRunningNodeIds: (ids: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  highlightedNodeIds: string[];
  hoveredPort: { nodeId: string; port: string; direction: "input" | "output" } | null;
  previewEdgeIds: string[];
  getPortTypeForHandle: (nodeId: string, handleId: string, role: "source" | "target") => any;
  getPortTypeColor: (portType: any) => string;
}

export const useNodeExecutionSync = ({
  nodes,
  edges,
  setNodes,
  setEdges,
  nodeStatuses,
  trace,
  isRunning,
  isInterrupting,
  runningNodeIds,
  setRunningNodeIds,
  highlightedNodeIds,
  hoveredPort,
  previewEdgeIds,
  getPortTypeForHandle,
  getPortTypeColor,
}: UseNodeExecutionSyncOptions) => {
  // Build a node lookup map for O(1) access instead of O(n) find() calls
  const nodeById = useMemo(() => {
    const map = new Map<string, typeof nodes[number]>();
    for (const node of nodes) map.set(node.id, node);
    return map;
  }, [nodes]);

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
        const newOutputs = traceEntry?.outputs ?? node.data.last_outputs;
        const newLogs = traceEntry?.logs ?? node.data.executionLogs;
        const newDuration = traceEntry?.duration_ms;

        // Early bailout - skip if nothing actually changed for this node
        if (
          node.data.executionStatus === status &&
          node.data.executionDuration === newDuration &&
          node.data.last_outputs === newOutputs &&
          node.data.executionLogs === newLogs
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
          },
        };
      })
    );
  }, [nodeStatuses, trace, isRunning, setNodes]);

  // Update edges for running state
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

        const loopDash = isLoopBodyEdge ? (isLoopRunning ? "2 4" : undefined) : (edge.style as React.CSSProperties | undefined)?.strokeDasharray;
        const newStrokeWidth = (isRunning && targetInRunningSet) ? 2.5 : 2;

        // Early bailout - skip if this edge's styling wouldn't change
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
  }, [isRunning, setRunningNodeIds]);

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
  }, [nodeStatuses, setRunningNodeIds]);

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
    const previewSet = new Set(previewEdgeIds);
    setEdges((existing) =>
      existing.map((edge) => {
        const shouldPreview = previewSet.has(edge.id);
        // Early bailout if preview state hasn't changed
        if ((edge.data as any)?.isPreview === shouldPreview) return edge;
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
  }, [getPortTypeForHandle, setEdges, getPortTypeColor]);

  return {
    nodeById,
  };
};
