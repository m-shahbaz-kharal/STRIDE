/**
 * Execution orchestration hook.
 *
 * Handles running graphs, managing execution state, and coordinating
 * cache invalidation. This is extracted from App.tsx to reduce its size.
 */

import { useCallback, useRef } from 'react';
import { Node, Edge } from 'reactflow';
import { authFetch } from '../api';
import { BlueprintNodeData, TypeDescriptor } from '../types';
import { getDownstreamNodes, getDependentNodes, getUpstreamNodes } from '../domain';

interface UseExecutionOrchestratorProps {
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  selectedNodeIds: string[];
  isRunning: boolean;
  useStreaming: boolean;
  setNodes: (nodes: Node<BlueprintNodeData>[] | ((nds: Node<BlueprintNodeData>[]) => Node<BlueprintNodeData>[])) => void;
  setRunningNodeIds: (ids: Set<string> | ((prev: Set<string>) => Set<string>)) => void;
  getPortTypeForHandle: (nodeId: string, handleId: string, role: 'source' | 'target') => TypeDescriptor;
  runGraph: (payload: any, runIds: string[]) => void;
  runGraphSync: (payload: any, runIds: string[]) => Promise<any>;
}

export const useExecutionOrchestrator = ({
  nodes,
  edges,
  selectedNodeIds,
  isRunning,
  useStreaming,
  setNodes,
  setRunningNodeIds,
  getPortTypeForHandle,
  runGraph,
  runGraphSync,
}: UseExecutionOrchestratorProps) => {
  // Track dirty cache nodes
  const dirtyCacheNodesRef = useRef<Set<string>>(new Set());

  /**
   * Clear UI-side cache state for nodes.
   */
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

  /**
   * Mark nodes as having dirty cache (will be invalidated on next run).
   */
  const markCacheDirtyForNodes = useCallback((nodeIds: Set<string>) => {
    if (nodeIds.size === 0) return;
    nodeIds.forEach((nodeId) => dirtyCacheNodesRef.current.add(nodeId));
    clearNodesCacheUI(nodeIds);
  }, [clearNodesCacheUI]);

  /**
   * Mark a node and all its downstream nodes as dirty.
   */
  const markNodeAndDownstreamDirty = useCallback((nodeId: string) => {
    const downstream = getDownstreamNodes([nodeId], edges);
    markCacheDirtyForNodes(downstream);
  }, [edges, markCacheDirtyForNodes]);

  /**
   * Clear backend cache for specific nodes.
   */
  const clearBackendCacheForNodes = useCallback(async (nodeIds: Iterable<string>) => {
    const uniqueIds = Array.from(new Set(nodeIds));
    if (uniqueIds.length === 0) return;
    try {
      await authFetch('/api/cache/clear-nodes', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ node_ids: uniqueIds }),
      });
    } catch (e) {
      console.error('Failed to clear backend cache for nodes:', e);
    }
  }, []);

  /**
   * Build the graph payload for execution.
   */
  const buildGraphPayload = useCallback(
    (
      mode: 'full' | 'selection' | 'from_node',
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
          const sourceType = getPortTypeForHandle(edge.source, edge.sourceHandle!, 'source');
          const targetType = getPortTypeForHandle(edge.target, edge.targetHandle!, 'target');
          const isControl = sourceType.kind === 'control' || targetType.kind === 'control';
          return {
            from_node: edge.source,
            from_port: edge.sourceHandle,
            to_node: edge.target,
            to_port: edge.targetHandle,
            kind: isControl ? 'control' : (edge.data as any)?.kind || 'data',
          };
        });

      const options: Record<string, unknown> = { mode };
      if (mode === 'selection' && targetNodes?.length) {
        options.target_nodes = targetNodes;
      }
      if (mode === 'from_node' && targetNodes?.length) {
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

  /**
   * Run the graph with the specified mode and options.
   */
  const handleRunGraph = useCallback(
    async (
      mode: 'full' | 'selection' | 'from_node',
      targetNodes?: string[],
      extras?: { max_steps?: number }
    ) => {
      if (nodes.length === 0) return;

      const resolvedTargets = targetNodes || (mode !== 'full' ? selectedNodeIds : undefined);
      const downstreamForRerun = mode === 'from_node'
        ? getDownstreamNodes(resolvedTargets?.length ? resolvedTargets : selectedNodeIds, edges)
        : null;

      // Helper to check if node has cached output
      const hasCachedOutput = (nodeId: string) => {
        const node = nodes.find((n) => n.id === nodeId);
        return Boolean(node?.data.last_outputs);
      };

      const runNodes = mode === 'full'
        ? new Set(nodes.map((n) => n.id))
        : mode === 'from_node'
          ? getDependentNodes(
              Array.from(downstreamForRerun ?? getDownstreamNodes(resolvedTargets || selectedNodeIds, edges)),
              edges,
              { includeCached: true, hasCachedOutput, getPortType: getPortTypeForHandle }
            )
          : getDependentNodes(resolvedTargets || selectedNodeIds, edges, { hasCachedOutput, getPortType: getPortTypeForHandle });

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
        resolvedTargets || (mode === 'selection' ? selectedNodeIds : undefined),
        {
          max_steps: extras?.max_steps,
          force_no_cache_nodes: Array.from(forceNoCacheNodes),
          invalidate_cache_nodes: Array.from(invalidateCacheNodes),
        }
      );

      const uiResetNodes = mode === 'selection'
        ? getUpstreamNodes(Array.from(runNodes), edges)
        : runNodes;

      setNodes((existing) =>
        existing.map((node) => ({
          ...node,
          data: {
            ...node.data,
            executionStatus: uiResetNodes.has(node.id) ? undefined : node.data.executionStatus,
            executionDuration: uiResetNodes.has(node.id) ? undefined : node.data.executionDuration,
          },
        }))
      );

      const runIds = Array.from(runNodes);

      dirtyNodesInRun.forEach((nodeId) => dirtyCacheNodesRef.current.delete(nodeId));

      if (useStreaming && !isRunning) {
        runGraph(payload, runIds);
      } else {
        await runGraphSync(payload, runIds);
      }
    },
    [
      buildGraphPayload,
      edges,
      isRunning,
      nodes,
      runGraph,
      runGraphSync,
      selectedNodeIds,
      setNodes,
      setRunningNodeIds,
      useStreaming,
      getPortTypeForHandle,
    ]
  );

  /**
   * Clear all backend cache.
   */
  const handleClearBackendCache = useCallback(async () => {
    try {
      const response = await authFetch('/api/cache/clear', { method: 'POST' });
      if (response.ok) {
        const data = await response.json();
        console.log(`Cleared ${data.cleared} cached entries`);
        dirtyCacheNodesRef.current.clear();
        // Clear all node cache UI
        clearNodesCacheUI(new Set(nodes.map((n) => n.id)));
      }
    } catch (e) {
      console.error('Failed to clear backend cache:', e);
    }
  }, [clearNodesCacheUI, nodes]);

  return {
    dirtyCacheNodesRef,
    clearNodesCacheUI,
    markCacheDirtyForNodes,
    markNodeAndDownstreamDirty,
    clearBackendCacheForNodes,
    buildGraphPayload,
    handleRunGraph,
    handleClearBackendCache,
  };
};
