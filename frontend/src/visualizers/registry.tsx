/**
 * Visualizer registry for dashboard widgets.
 *
 * Phase 4 — full per-type inventory landed:
 *   - ``image`` / ``stream`` → ImageVisualizer (with overlay support)
 *   - ``detections2d`` → Detections2DVisualizer (table fallback; defers to
 *     ImageVisualizer when an image is present in the payload or composition)
 *   - ``keypoints``   → KeypointsVisualizer (skeleton-only fallback; defers
 *     to ImageVisualizer when an image is in the composition)
 *   - ``mask``        → MaskVisualizer (image fallback; defers when image
 *     overlay is present)
 *   - ``depthmap``    → DepthMapVisualizer (interactive false-color heatmap)
 *   - ``pointcloud`` / ``scene3d`` / ``detections3d`` / ``track3d`` /
 *     ``bbox3d`` / ``region3d`` → Scene3DVisualizer (the R3F powerhouse)
 *   - everything else → JSON dump fallback
 *
 * Reference: docs/architecture/unified-type-system-and-ux.md §8 (visualizer
 * registry) and §8.4 (composition).
 */

import React from "react";
import { Scene3DVisualizer } from "./Scene3DVisualizer";
import { ImageVisualizer } from "./ImageVisualizer";
import { DepthMapVisualizer } from "./DepthMapVisualizer";
import { Detections2DVisualizer } from "./Detections2DVisualizer";
import { KeypointsVisualizer } from "./KeypointsVisualizer";
import { MaskVisualizer } from "./MaskVisualizer";
import {
  isDepthMap,
  isDetections2D,
  isDetections3D,
  isImageString,
  isKeypoints,
  isMask,
  isPointCloud,
  isRegion3D,
  isScene3D,
  isTrack3D,
  isBBox3D,
} from "./_lib/types";

/**
 * Props passed to every visualizer.
 *
 * ``value`` is the primary payload at the bound port.
 * ``overlays`` is an optional list of extra payloads composed on top
 * (e.g. an image plus detections + keypoints; or a pointcloud plus
 * detections3d + tracks). The visualizer is free to merge them.
 * ``label`` is the optional widget label.
 */
export interface VisualizerProps {
  value: unknown;
  overlays?: unknown[];
  label?: string;
}

export interface VisualizerSpec {
  /** Type kind this entry handles, or ``"*"`` for the universal fallback. */
  kind: string;
  /** Higher priority wins ties. Default 0. */
  priority: number;
  /** Runtime guard. Returning false skips this entry. */
  match: (value: unknown) => boolean;
  /** React component that renders the value. */
  Component: React.FC<VisualizerProps>;
}

// ===========================================================================
// Stream wrapper — same logic as Phase 0 (live frame poll), now isolated.
// ===========================================================================

const StreamFrame: React.FC<VisualizerProps> = ({ value }) => {
  const stream = value as { stream_id: string };
  return (
    <div style={{ width: "100%", height: "100%", position: "relative", background: "#000" }}>
      <img
        src={`/api/streams/${stream.stream_id}/frame?ts=${Date.now()}`}
        alt="stream"
        style={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    </div>
  );
};

// ===========================================================================
// JSON dump fallback (preserved from Phase 0).
// ===========================================================================

const JsonDumpVisualizer: React.FC<VisualizerProps> = ({ value, label }) => (
  <div style={{ width: "100%", height: "100%", display: "flex", flexDirection: "column" }}>
    {label && (
      <div style={{ fontSize: "11px", color: "var(--text-muted)", marginBottom: "4px" }}>
        {label}
      </div>
    )}
    <div
      style={{
        flex: 1,
        background: "var(--bg-tertiary)",
        padding: "8px",
        borderRadius: "4px",
        overflow: "auto",
        fontFamily: "monospace",
        whiteSpace: "pre-wrap",
        fontSize: 11,
        color: "var(--text-primary)",
      }}
    >
      {value !== undefined && value !== null ? (
        typeof value === "object" ? (
          JSON.stringify(value, null, 2)
        ) : (
          String(value)
        )
      ) : (
        <span style={{ opacity: 0.5 }}>No Data</span>
      )}
    </div>
  </div>
);

// ===========================================================================
// Registry
// ===========================================================================

/**
 * Live registry. Order does not matter for resolution — entries are sorted
 * by priority at lookup time.
 */
export const VISUALIZER_REGISTRY: VisualizerSpec[] = [
  // ---------- 3-D family — all flow through Scene3DVisualizer ----------
  { kind: "scene3d", priority: 20, match: isScene3D, Component: Scene3DVisualizer },
  { kind: "pointcloud", priority: 20, match: isPointCloud, Component: Scene3DVisualizer },
  { kind: "detections3d", priority: 20, match: isDetections3D, Component: Scene3DVisualizer },
  { kind: "track3d", priority: 20, match: isTrack3D, Component: Scene3DVisualizer },
  { kind: "region3d", priority: 15, match: isRegion3D, Component: Scene3DVisualizer },
  { kind: "bbox3d", priority: 10, match: isBBox3D, Component: Scene3DVisualizer },
  // ---------- 2-D image-domain ----------
  { kind: "image", priority: 20, match: isImageString, Component: ImageVisualizer },
  {
    kind: "image",
    priority: 21,
    match: (v) => !!v && typeof v === "object" && (v as { _type?: string })._type === "Image",
    Component: ImageVisualizer,
  },
  { kind: "detections2d", priority: 20, match: isDetections2D, Component: Detections2DVisualizer },
  { kind: "keypoints", priority: 20, match: isKeypoints, Component: KeypointsVisualizer },
  { kind: "mask", priority: 20, match: isMask, Component: MaskVisualizer },
  { kind: "depthmap", priority: 20, match: isDepthMap, Component: DepthMapVisualizer },
  // ---------- Stream ----------
  {
    kind: "stream",
    priority: 20,
    match: (v) => !!v && typeof v === "object" && (v as { _type?: string })._type === "StreamResource",
    Component: StreamFrame,
  },
  // ---------- Universal fallback ----------
  { kind: "*", priority: -1, match: () => true, Component: JsonDumpVisualizer },
];

/**
 * Append a visualizer to the registry. Used by build-time-discovered
 * ``stride.visualizer.json`` manifests in Phase 5; can also be called by
 * application code at startup.
 */
export function registerVisualizer(spec: VisualizerSpec): void {
  VISUALIZER_REGISTRY.push(spec);
}

/**
 * Resolve the best visualizer for ``(typeKind, payload)``.
 *
 * Resolution order:
 *   1. If ``typeKind !== "*"``: filter to specs with ``kind === typeKind``;
 *      pick the highest priority that ``match()``-es the payload.
 *   2. Otherwise (Phase 0/1 path or unknown port type): consider every
 *      kind-specific spec, picking by ``match()`` + priority.
 *   3. Fall through to the ``"*"`` fallback if no spec matched.
 */
export function resolveVisualizer(typeKind: string, payload?: unknown): VisualizerSpec | null {
  const consider = (specs: VisualizerSpec[]): VisualizerSpec | null => {
    const matches = specs.filter((s) => {
      try {
        return s.match(payload);
      } catch {
        return false;
      }
    });
    if (matches.length === 0) return null;
    matches.sort((a, b) => b.priority - a.priority);
    return matches[0];
  };

  if (typeKind && typeKind !== "*") {
    const kindSpecific = VISUALIZER_REGISTRY.filter((s) => s.kind === typeKind);
    const winner = consider(kindSpecific);
    if (winner) return winner;
  }

  if (typeKind === "*") {
    const nonFallback = VISUALIZER_REGISTRY.filter((s) => s.kind !== "*");
    const winner = consider(nonFallback);
    if (winner) return winner;
  }

  const fallbacks = VISUALIZER_REGISTRY.filter((s) => s.kind === "*");
  return consider(fallbacks);
}

// ===========================================================================
// Composition (§8.4)
// ===========================================================================

/**
 * Composite visualizer — picks the registry entry that should "host" the
 * primary value, then renders it with all overlays passed through.
 *
 * The host visualizer decides how to merge: e.g. ``ImageVisualizer`` paints
 * ``detections2d``/``keypoints``/``mask`` over the image; ``Scene3DVisualizer``
 * merges any combination of pointcloud + detections3d + tracks + regions in
 * one scene.
 *
 * If no overlays are bound, this is equivalent to ``resolveVisualizer``.
 */
export const CompositeVisualizer: React.FC<VisualizerProps> = ({ value, overlays, label }) => {
  // For composition, the primary value drives the choice. Scene3D types win
  // over 2-D types because the composition is more visual when 3-D content is
  // available; same for image+detections deferring to ImageVisualizer.
  let primary = value;
  // If primary is null but overlays carry a useful payload, hoist that.
  if ((value === null || value === undefined) && overlays && overlays.length) {
    primary = overlays.find((o) => o !== null && o !== undefined) ?? value;
  }
  const spec = resolveVisualizer("*", primary);
  if (!spec) return null;
  const Vis = spec.Component;
  return <Vis value={primary} overlays={overlays} label={label} />;
};
