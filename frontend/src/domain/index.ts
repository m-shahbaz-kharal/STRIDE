/**
 * Domain layer for LiGuard-Web frontend.
 *
 * This module contains pure domain logic that is independent of React/UI concerns:
 * - Type descriptors and compatibility rules
 * - Graph traversal utilities
 *
 * By extracting this logic from React hooks, we can:
 * - Unit test the logic independently
 * - Reuse it across different UI components
 * - Keep the mental model clear
 */

export type { TypeDescriptor } from './types';
export { normalizeType, areTypesCompatible, getTypeLabel } from './types';
export { getDependentNodes, getDownstreamNodes, getUpstreamNodes } from './graph-utils';
export type { PortConnection } from './graph-utils';
