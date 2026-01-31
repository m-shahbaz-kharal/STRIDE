/**
 * Graph traversal utilities.
 *
 * Pure functions for traversing the node graph. These are extracted from
 * App.tsx to enable unit testing and reuse.
 */

import { Edge } from 'reactflow';
import { TypeDescriptor, isControlType } from './types';

/**
 * Represents a connection between two ports.
 */
export interface PortConnection {
  source: string;
  sourceHandle: string;
  target: string;
  targetHandle: string;
  kind?: 'data' | 'control';
}

/**
 * Interface for a minimal node with last_outputs for cache checking.
 */
interface NodeWithOutputs {
  id: string;
  data: {
    last_outputs?: Record<string, unknown>;
  };
}

/**
 * Get all upstream dependency nodes (nodes that must execute before the target).
 *
 * This traverses backward through the graph following data and control edges
 * to find all nodes that the target nodes depend on.
 *
 * @param targetNodeIds - The nodes to find dependencies for
 * @param edges - All edges in the graph
 * @param options - Optional configuration
 * @returns Set of node IDs that are upstream dependencies
 */
export function getDependentNodes(
  targetNodeIds: string[],
  edges: Edge[],
  options: {
    /**
     * If true, include nodes that have cached outputs in the dependency chain.
     * If false (default), stop at nodes that have cached results.
     */
    includeCached?: boolean;
    /**
     * Function to check if a node has cached outputs.
     */
    hasCachedOutput?: (nodeId: string) => boolean;
    /**
     * Function to get the port type for a handle (for control flow detection).
     */
    getPortType?: (nodeId: string, handleId: string, role: 'source' | 'target') => TypeDescriptor;
  } = {}
): Set<string> {
  const { includeCached = false, hasCachedOutput, getPortType } = options;

  const dependentIds = new Set<string>(targetNodeIds);
  const visited = new Set<string>();
  const queue = [...targetNodeIds];

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    if (visited.has(nodeId)) continue;
    visited.add(nodeId);

    for (const edge of edges) {
      if (edge.target !== nodeId) continue;
      if (dependentIds.has(edge.source)) continue;

      // Determine if this is a control edge
      let isControl = edge.data?.kind === 'control';
      if (!isControl && edge.sourceHandle && edge.targetHandle && getPortType) {
        const sourceType = getPortType(edge.source, edge.sourceHandle, 'source');
        const targetType = getPortType(edge.target, edge.targetHandle, 'target');
        isControl = isControlType(sourceType) || isControlType(targetType);
      }

      // Control edges always included; data edges check cache
      const hasCache = hasCachedOutput ? hasCachedOutput(edge.source) : false;
      if (isControl || includeCached || !hasCache) {
        dependentIds.add(edge.source);
        queue.push(edge.source);
      }
    }
  }

  return dependentIds;
}

/**
 * Get all downstream nodes (nodes that depend on the start nodes).
 *
 * This traverses forward through the graph following data and control edges
 * to find all nodes that will be affected by changes to the start nodes.
 *
 * @param startNodeIds - The nodes to find dependents for
 * @param edges - All edges in the graph
 * @returns Set of node IDs that are downstream dependents (includes start nodes)
 */
export function getDownstreamNodes(startNodeIds: string[], edges: Edge[]): Set<string> {
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
}

/**
 * Get all upstream nodes (nodes that the target depends on directly or indirectly).
 *
 * @param targetNodeIds - The nodes to find dependencies for
 * @param edges - All edges in the graph
 * @returns Set of node IDs that are upstream (includes target nodes)
 */
export function getUpstreamNodes(targetNodeIds: string[], edges: Edge[]): Set<string> {
  const upstream = new Set<string>(targetNodeIds);
  const queue = [...targetNodeIds];

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    for (const edge of edges) {
      if (edge.target === nodeId && !upstream.has(edge.source)) {
        upstream.add(edge.source);
        queue.push(edge.source);
      }
    }
  }

  return upstream;
}

/**
 * Get the topological level of each node (for parallel execution).
 *
 * Nodes at level 0 have no dependencies. Nodes at level N depend only
 * on nodes at levels 0 to N-1.
 *
 * @param nodeIds - All node IDs in the graph
 * @param edges - All edges in the graph
 * @returns Map of node ID to level number
 */
export function computeNodeLevels(nodeIds: string[], edges: Edge[]): Map<string, number> {
  const levels = new Map<string, number>();
  const inDegree = new Map<string, number>();
  const dependents = new Map<string, string[]>();

  // Initialize
  for (const nodeId of nodeIds) {
    inDegree.set(nodeId, 0);
    dependents.set(nodeId, []);
  }

  // Build dependency graph
  for (const edge of edges) {
    if (!inDegree.has(edge.source) || !inDegree.has(edge.target)) continue;
    inDegree.set(edge.target, (inDegree.get(edge.target) ?? 0) + 1);
    const deps = dependents.get(edge.source) ?? [];
    deps.push(edge.target);
    dependents.set(edge.source, deps);
  }

  // BFS to compute levels
  const queue: string[] = [];
  for (const [nodeId, degree] of inDegree.entries()) {
    if (degree === 0) {
      levels.set(nodeId, 0);
      queue.push(nodeId);
    }
  }

  while (queue.length > 0) {
    const nodeId = queue.shift()!;
    const nodeLevel = levels.get(nodeId) ?? 0;

    for (const dependent of dependents.get(nodeId) ?? []) {
      const newDegree = (inDegree.get(dependent) ?? 1) - 1;
      inDegree.set(dependent, newDegree);

      // Level is max of all dependency levels + 1
      const currentLevel = levels.get(dependent) ?? 0;
      levels.set(dependent, Math.max(currentLevel, nodeLevel + 1));

      if (newDegree === 0) {
        queue.push(dependent);
      }
    }
  }

  return levels;
}

/**
 * Group nodes by their level for parallel execution.
 *
 * @param nodeIds - All node IDs in the graph
 * @param edges - All edges in the graph
 * @returns Array of arrays, where index is the level and value is node IDs at that level
 */
export function groupNodesByLevel(nodeIds: string[], edges: Edge[]): string[][] {
  const nodeLevels = computeNodeLevels(nodeIds, edges);
  const levels: string[][] = [];

  for (const [nodeId, level] of nodeLevels.entries()) {
    while (levels.length <= level) {
      levels.push([]);
    }
    levels[level].push(nodeId);
  }

  return levels;
}

/**
 * Find all paths between two nodes.
 *
 * @param fromNodeId - Starting node
 * @param toNodeId - Ending node
 * @param edges - All edges in the graph
 * @param maxPaths - Maximum number of paths to find (default 100)
 * @returns Array of paths, where each path is an array of node IDs
 */
export function findPaths(
  fromNodeId: string,
  toNodeId: string,
  edges: Edge[],
  maxPaths: number = 100
): string[][] {
  const paths: string[][] = [];
  const stack: { nodeId: string; path: string[] }[] = [{ nodeId: fromNodeId, path: [fromNodeId] }];

  while (stack.length > 0 && paths.length < maxPaths) {
    const { nodeId, path } = stack.pop()!;

    if (nodeId === toNodeId) {
      paths.push([...path]);
      continue;
    }

    for (const edge of edges) {
      if (edge.source === nodeId && !path.includes(edge.target)) {
        stack.push({ nodeId: edge.target, path: [...path, edge.target] });
      }
    }
  }

  return paths;
}

/**
 * Check if there's a cycle in the graph.
 *
 * @param nodeIds - All node IDs in the graph
 * @param edges - All edges in the graph
 * @returns True if there's a cycle
 */
export function hasCycle(nodeIds: string[], edges: Edge[]): boolean {
  const WHITE = 0; // Not visited
  const GRAY = 1; // Being processed
  const BLACK = 2; // Done processing

  const color = new Map<string, number>();
  const adjacency = new Map<string, string[]>();

  // Initialize
  for (const nodeId of nodeIds) {
    color.set(nodeId, WHITE);
    adjacency.set(nodeId, []);
  }

  // Build adjacency list
  for (const edge of edges) {
    const adj = adjacency.get(edge.source);
    if (adj) {
      adj.push(edge.target);
    }
  }

  // DFS to detect cycle
  function dfs(nodeId: string): boolean {
    color.set(nodeId, GRAY);

    for (const neighbor of adjacency.get(nodeId) ?? []) {
      const neighborColor = color.get(neighbor) ?? WHITE;
      if (neighborColor === GRAY) {
        return true; // Back edge = cycle
      }
      if (neighborColor === WHITE && dfs(neighbor)) {
        return true;
      }
    }

    color.set(nodeId, BLACK);
    return false;
  }

  for (const nodeId of nodeIds) {
    if (color.get(nodeId) === WHITE && dfs(nodeId)) {
      return true;
    }
  }

  return false;
}
