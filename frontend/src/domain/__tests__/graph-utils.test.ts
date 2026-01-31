/**
 * Tests for graph utility functions.
 *
 * @jest-environment jsdom
 */

import { describe, it, expect } from 'vitest';
import { Edge } from 'reactflow';
import {
  getDependentNodes,
  getDownstreamNodes,
  getUpstreamNodes,
  computeNodeLevels,
  groupNodesByLevel,
  findPaths,
  hasCycle,
} from '../graph-utils';

/**
 * Helper to create mock edges.
 */
function makeEdge(source: string, target: string, kind?: 'data' | 'control'): Edge {
  return {
    id: `${source}-${target}`,
    source,
    target,
    sourceHandle: 'output',
    targetHandle: 'input',
    data: kind ? { kind } : undefined,
  };
}

describe('getDownstreamNodes', () => {
  it('should return start nodes for empty graph', () => {
    const result = getDownstreamNodes(['a'], []);
    expect(result).toEqual(new Set(['a']));
  });

  it('should find direct dependents', () => {
    // a -> b
    const edges = [makeEdge('a', 'b')];
    const result = getDownstreamNodes(['a'], edges);
    expect(result).toEqual(new Set(['a', 'b']));
  });

  it('should find transitive dependents', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const result = getDownstreamNodes(['a'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });

  it('should handle diamond patterns', () => {
    //     b
    //    / \
    // a      d
    //    \ /
    //     c
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'd'),
      makeEdge('c', 'd'),
    ];
    const result = getDownstreamNodes(['a'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c', 'd']));
  });

  it('should handle multiple start nodes', () => {
    // a -> c
    // b -> c
    const edges = [makeEdge('a', 'c'), makeEdge('b', 'c')];
    const result = getDownstreamNodes(['a', 'b'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });
});

describe('getUpstreamNodes', () => {
  it('should return target nodes for empty graph', () => {
    const result = getUpstreamNodes(['c'], []);
    expect(result).toEqual(new Set(['c']));
  });

  it('should find direct dependencies', () => {
    // a -> b
    const edges = [makeEdge('a', 'b')];
    const result = getUpstreamNodes(['b'], edges);
    expect(result).toEqual(new Set(['a', 'b']));
  });

  it('should find transitive dependencies', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const result = getUpstreamNodes(['c'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });

  it('should handle multiple targets', () => {
    // a -> b
    // a -> c
    const edges = [makeEdge('a', 'b'), makeEdge('a', 'c')];
    const result = getUpstreamNodes(['b', 'c'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });
});

describe('getDependentNodes', () => {
  it('should return target nodes when no dependencies', () => {
    const result = getDependentNodes(['a'], []);
    expect(result).toEqual(new Set(['a']));
  });

  it('should find upstream dependencies', () => {
    // a -> b -> c (we want dependencies of c)
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const result = getDependentNodes(['c'], edges);
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });

  it('should stop at cached nodes by default', () => {
    // a -> b -> c (b is cached)
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const hasCachedOutput = (nodeId: string) => nodeId === 'b';
    const result = getDependentNodes(['c'], edges, { hasCachedOutput });
    expect(result).toEqual(new Set(['b', 'c']));
  });

  it('should include cached nodes when includeCached is true', () => {
    // a -> b -> c (b is cached)
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const hasCachedOutput = (nodeId: string) => nodeId === 'b';
    const result = getDependentNodes(['c'], edges, { includeCached: true, hasCachedOutput });
    expect(result).toEqual(new Set(['a', 'b', 'c']));
  });
});

describe('computeNodeLevels', () => {
  it('should assign level 0 to nodes with no dependencies', () => {
    const levels = computeNodeLevels(['a', 'b', 'c'], []);
    expect(levels.get('a')).toBe(0);
    expect(levels.get('b')).toBe(0);
    expect(levels.get('c')).toBe(0);
  });

  it('should compute levels for linear chain', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const levels = computeNodeLevels(['a', 'b', 'c'], edges);
    expect(levels.get('a')).toBe(0);
    expect(levels.get('b')).toBe(1);
    expect(levels.get('c')).toBe(2);
  });

  it('should compute max level for diamond pattern', () => {
    //     b (level 1)
    //    / \
    // a      d (level 2)
    //    \ /
    //     c (level 1)
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'd'),
      makeEdge('c', 'd'),
    ];
    const levels = computeNodeLevels(['a', 'b', 'c', 'd'], edges);
    expect(levels.get('a')).toBe(0);
    expect(levels.get('b')).toBe(1);
    expect(levels.get('c')).toBe(1);
    expect(levels.get('d')).toBe(2);
  });
});

describe('groupNodesByLevel', () => {
  it('should group nodes by their computed level', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const groups = groupNodesByLevel(['a', 'b', 'c'], edges);

    expect(groups.length).toBe(3);
    expect(groups[0]).toContain('a');
    expect(groups[1]).toContain('b');
    expect(groups[2]).toContain('c');
  });

  it('should put parallel nodes at same level', () => {
    // a -> [b, c] -> d
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'd'),
      makeEdge('c', 'd'),
    ];
    const groups = groupNodesByLevel(['a', 'b', 'c', 'd'], edges);

    expect(groups[0]).toContain('a');
    expect(groups[1]).toContain('b');
    expect(groups[1]).toContain('c');
    expect(groups[2]).toContain('d');
  });
});

describe('findPaths', () => {
  it('should find direct path', () => {
    // a -> b
    const edges = [makeEdge('a', 'b')];
    const paths = findPaths('a', 'b', edges);
    expect(paths).toEqual([['a', 'b']]);
  });

  it('should find transitive path', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    const paths = findPaths('a', 'c', edges);
    expect(paths).toEqual([['a', 'b', 'c']]);
  });

  it('should find multiple paths in diamond', () => {
    //     b
    //    / \
    // a      d
    //    \ /
    //     c
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'd'),
      makeEdge('c', 'd'),
    ];
    const paths = findPaths('a', 'd', edges);
    expect(paths.length).toBe(2);
    expect(paths).toContainEqual(['a', 'b', 'd']);
    expect(paths).toContainEqual(['a', 'c', 'd']);
  });

  it('should return empty for no path', () => {
    // a    b (disconnected)
    const paths = findPaths('a', 'b', []);
    expect(paths).toEqual([]);
  });

  it('should limit number of paths', () => {
    // Create a graph with many paths
    const edges = [
      makeEdge('a', 'b1'),
      makeEdge('a', 'b2'),
      makeEdge('a', 'b3'),
      makeEdge('b1', 'c'),
      makeEdge('b2', 'c'),
      makeEdge('b3', 'c'),
    ];
    const paths = findPaths('a', 'c', edges, 2);
    expect(paths.length).toBe(2);
  });
});

describe('hasCycle', () => {
  it('should return false for empty graph', () => {
    expect(hasCycle([], [])).toBe(false);
  });

  it('should return false for linear graph', () => {
    // a -> b -> c
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'c')];
    expect(hasCycle(['a', 'b', 'c'], edges)).toBe(false);
  });

  it('should return false for DAG', () => {
    //     b
    //    / \
    // a      d
    //    \ /
    //     c
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'd'),
      makeEdge('c', 'd'),
    ];
    expect(hasCycle(['a', 'b', 'c', 'd'], edges)).toBe(false);
  });

  it('should return true for simple cycle', () => {
    // a -> b -> a
    const edges = [makeEdge('a', 'b'), makeEdge('b', 'a')];
    expect(hasCycle(['a', 'b'], edges)).toBe(true);
  });

  it('should return true for longer cycle', () => {
    // a -> b -> c -> a
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('b', 'c'),
      makeEdge('c', 'a'),
    ];
    expect(hasCycle(['a', 'b', 'c'], edges)).toBe(true);
  });

  it('should detect cycle in larger graph', () => {
    //     b -> e
    //    /      \
    // a          f
    //    \      /
    //     c -> d (with d -> b creating cycle)
    const edges = [
      makeEdge('a', 'b'),
      makeEdge('a', 'c'),
      makeEdge('b', 'e'),
      makeEdge('c', 'd'),
      makeEdge('d', 'f'),
      makeEdge('e', 'f'),
      makeEdge('d', 'b'), // Cycle!
    ];
    expect(hasCycle(['a', 'b', 'c', 'd', 'e', 'f'], edges)).toBe(true);
  });
});
