/**
 * useGraphDependencies - Graph dependency and cache tracking utilities
 * 
 * Extracted from App.tsx to provide reusable graph traversal functions
 * for determining upstream/downstream dependencies and managing cache state.
 */

import { useCallback, useRef } from "react";
import { Edge, Node } from "reactflow";
import { BlueprintNodeData, TypeDescriptor } from "../types";

interface UseGraphDependenciesProps {
    nodes: Node<BlueprintNodeData>[];
    edges: Edge[];
    setNodes: React.Dispatch<React.SetStateAction<Node<BlueprintNodeData>[]>>;
    getPortTypeForHandle: (
        nodeId: string,
        handleId: string,
        handleType: "source" | "target"
    ) => TypeDescriptor;
}

interface UseGraphDependenciesReturn {
    /** Track nodes whose cache needs invalidation */
    dirtyCacheNodesRef: React.MutableRefObject<Set<string>>;
    /** Get all upstream dependencies for target nodes */
    getDependentNodes: (targetNodeIds: string[], includeCached?: boolean) => Set<string>;
    /** Get all downstream nodes from start nodes */
    getDownstreamNodes: (startNodeIds: string[]) => Set<string>;
    /** Clear cache UI state for nodes */
    clearNodesCacheUI: (nodeIds: Set<string>) => void;
    /** Mark nodes as needing cache invalidation */
    markCacheDirtyForNodes: (nodeIds: Set<string>) => void;
    /** Mark a node and all its downstream nodes as dirty */
    markNodeAndDownstreamDirty: (nodeId: string) => void;
    /** Clear backend cache for a set of nodes */
    clearBackendCacheForNodes: (nodeIds: Iterable<string>) => Promise<void>;
}

export function useGraphDependencies({
    nodes,
    edges,
    setNodes,
    getPortTypeForHandle,
}: UseGraphDependenciesProps): UseGraphDependenciesReturn {
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

    // Get all upstream dependencies for target nodes
    const getDependentNodes = useCallback(
        (targetNodeIds: string[], includeCached = false): Set<string> => {
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
                        let isControl = edge.data?.kind === "control";
                        if (!isControl && edge.sourceHandle && edge.targetHandle) {
                            const sourceType = getPortTypeForHandle(edge.source, edge.sourceHandle, "source");
                            const targetType = getPortTypeForHandle(edge.target, edge.targetHandle, "target");
                            isControl = sourceType.kind === "control" || targetType.kind === "control";
                        }
                        if (isControl || includeCached || !sourceNode?.data.last_outputs) {
                            dependentIds.add(edge.source);
                            queue.push(edge.source);
                        }
                    }
                }
            }

            return dependentIds;
        },
        [edges, getPortTypeForHandle, nodes]
    );

    // Get all downstream nodes from start nodes
    const getDownstreamNodes = useCallback(
        (startNodeIds: string[]): Set<string> => {
            const downstream = new Set<string>(startNodeIds);
            const queue = [...startNodeIds];

            while (queue.length > 0) {
                const nodeId = queue.shift()!;
                for (const edge of edges) {
                    if (edge.source === nodeId && !downstream.has(edge.target)) {
                        downstream.add(edge.target);
                        queue.push(edge.target);
                    }
                }
            }

            return downstream;
        },
        [edges]
    );

    // Clear cache UI state for nodes
    const clearNodesCacheUI = useCallback(
        (nodeIds: Set<string>) => {
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
        },
        [setNodes]
    );

    // Mark nodes as needing cache invalidation
    const markCacheDirtyForNodes = useCallback(
        (nodeIds: Set<string>) => {
            if (nodeIds.size === 0) return;
            nodeIds.forEach((nodeId) => dirtyCacheNodesRef.current.add(nodeId));
            clearNodesCacheUI(nodeIds);
        },
        [clearNodesCacheUI]
    );

    // Mark a node and all its downstream nodes as dirty
    const markNodeAndDownstreamDirty = useCallback(
        (nodeId: string) => {
            const downstream = getDownstreamNodes([nodeId]);
            markCacheDirtyForNodes(downstream);
        },
        [getDownstreamNodes, markCacheDirtyForNodes]
    );

    return {
        dirtyCacheNodesRef,
        getDependentNodes,
        getDownstreamNodes,
        clearNodesCacheUI,
        markCacheDirtyForNodes,
        markNodeAndDownstreamDirty,
        clearBackendCacheForNodes,
    };
}
