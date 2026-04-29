/**
 * Visualizer registry for dashboard widgets.
 *
 * Phase 0: replaces the hand-coded if/else chain in
 * `DashboardWidgetContent.tsx` (the previous `case "bound-output"` body)
 * with a registry keyed on type kind. Functionally identical to the old
 * chain — every value that rendered as an `<img>` still renders as an
 * `<img>`; every value that fell through to the JSON dump still falls
 * through to the JSON dump.
 *
 * Reference:
 *   docs/architecture/unified-type-system-and-ux.md §8 (visualiser registry)
 *
 * Phase 1+ will:
 *   - move per-type visualizers (image, mask, depthmap, ...) into their
 *     own files under this folder,
 *   - introduce build-time discovery via `stride.visualizer.json` (§8.2),
 *   - add the composition visualizer (§8.4).
 *
 * For Phase 0 the registry intentionally only mirrors the four existing
 * special cases plus the JSON-dump fallback. Adding new visualizers
 * belongs to Phase 4.
 */

import React from "react";
import { PointCloudWidget } from "../components/dashboard/PointCloudWidget";
import { Scene3DWidget } from "../components/dashboard/Scene3DWidget";

/**
 * Props passed to a visualizer component. ``value`` is the raw payload at
 * the bound output port. ``label`` is the optional widget label, used by
 * the JSON-dump fallback to render its header.
 *
 * The full ``VisualizerProps`` from doc §8.2 (with ``type``, ``width``,
 * ``height``, ``context``) lands in Phase 1+ when the schema-aware
 * visualizers arrive. Phase 0 keeps the surface minimal so the refactor
 * is byte-equivalent to the prior if/else chain.
 */
export interface VisualizerProps {
  value: unknown;
  /** Widget label, used only by the JSON-dump fallback's header. */
  label?: string;
}

/**
 * A single registry entry. ``kind`` is the matched ``TypeKind`` (or the
 * special ``"*"`` fallback). ``priority`` resolves ties — higher wins.
 * ``match`` is the runtime guard: returns true if the visualizer can
 * actually render the given payload.
 */
export interface VisualizerSpec {
  /** Type kind this entry handles, or ``"*"`` for the universal fallback. */
  kind: string;
  /** Optional subtype refinement (Phase 1+). Unused in Phase 0. */
  subtype?: string;
  /** Higher priority wins ties. Default 0. */
  priority: number;
  /** Runtime guard. Returning false skips this entry. */
  match: (value: unknown) => boolean;
  /** React component that renders the value. */
  Component: React.FC<VisualizerProps>;
}

// ===========================================================================
// Components
// ---------------------------------------------------------------------------
// Each component below corresponds to one branch of the previous if/else
// chain in DashboardWidgetContent.tsx (case "bound-output"). The DOM these
// emit is byte-identical to what the old code emitted.
// ===========================================================================

const ImageVisualizer: React.FC<VisualizerProps> = ({ value }) => (
  <img
    src={value as string}
    alt="output"
    style={{ width: "100%", height: "100%", objectFit: "contain" }}
  />
);

const StreamVisualizer: React.FC<VisualizerProps> = ({ value }) => {
  const stream = value as { stream_id: string };
  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#000",
      }}
    >
      <img
        src={`/api/streams/${stream.stream_id}/frame?ts=${Date.now()}`}
        alt="stream"
        style={{ width: "100%", height: "100%", objectFit: "contain" }}
      />
    </div>
  );
};

const Scene3DVisualizer: React.FC<VisualizerProps> = ({ value }) => (
  <Scene3DWidget data={value as Parameters<typeof Scene3DWidget>[0]["data"]} />
);

const PointCloudVisualizer: React.FC<VisualizerProps> = ({ value }) => (
  <PointCloudWidget data={value as Parameters<typeof PointCloudWidget>[0]["data"]} />
);

/**
 * JSON-dump fallback. Identical DOM/CSS to the previous else-branch in
 * ``DashboardWidgetContent.tsx`` so existing widgets keep their look.
 */
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
 *
 * Use :func:`registerVisualizer` to append entries from outside this file
 * (Phase 1+ will populate this from ``stride.visualizer.json`` manifests).
 */
export const VISUALIZER_REGISTRY: VisualizerSpec[] = [
  {
    kind: "image",
    priority: 10,
    match: (v) =>
      typeof v === "string" && (v.startsWith("data:image") || v.startsWith("http")),
    Component: ImageVisualizer,
  },
  {
    kind: "stream",
    priority: 10,
    match: (v) =>
      !!v && typeof v === "object" && (v as { _type?: string })._type === "StreamResource",
    Component: StreamVisualizer,
  },
  {
    kind: "scene3d",
    priority: 10,
    match: (v) =>
      !!v && typeof v === "object" && (v as { _type?: string })._type === "Scene3D",
    Component: Scene3DVisualizer,
  },
  {
    kind: "pointcloud",
    priority: 10,
    match: (v) =>
      !!v && typeof v === "object" && (v as { _type?: string })._type === "PointCloud",
    Component: PointCloudVisualizer,
  },
  {
    // Universal fallback. Always matches.
    kind: "*",
    priority: -1,
    match: () => true,
    Component: JsonDumpVisualizer,
  },
];

/**
 * Append a visualizer to the registry. Phase 1+ will use this from build-
 * time discovery; Phase 0 has no consumers but the function is part of the
 * permanent contract per doc §8.2.
 */
export function registerVisualizer(spec: VisualizerSpec): void {
  VISUALIZER_REGISTRY.push(spec);
}

/**
 * Resolve the best visualizer for ``(typeKind, payload)``.
 *
 * Resolution order (per doc §8.2 — adapted to the Phase 0 surface):
 *   1. Filter to specs where ``kind === typeKind`` (kind-specific entries).
 *   2. Filter by ``match(payload)`` returning true.
 *   3. Sort by ``priority`` desc, take the first.
 *   4. If none, fall through to ``kind === "*"`` fallback specs and repeat.
 *   5. If still none (impossible while the JSON-dump fallback is registered),
 *      return ``null``.
 *
 * The Phase 0 caller in ``DashboardWidgetContent.tsx`` does not yet have
 * a reliable type-kind context — it inspects ``value`` shape — so in
 * practice it passes ``"*"`` and lets the ``match`` callbacks discriminate.
 * Phase 1+ will pass real type kinds resolved from the bound port type.
 */
export function resolveVisualizer(
  typeKind: string,
  payload?: unknown,
): VisualizerSpec | null {
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

  // 1. Kind-specific entries.
  if (typeKind && typeKind !== "*") {
    const kindSpecific = VISUALIZER_REGISTRY.filter((s) => s.kind === typeKind);
    const winner = consider(kindSpecific);
    if (winner) return winner;
  }

  // 2. When the caller passed "*" (Phase 0 path) we still want the
  //    kind-specific entries to have a shot, because their match()
  //    discriminates by payload shape. So consider them here too.
  if (typeKind === "*") {
    const nonFallback = VISUALIZER_REGISTRY.filter((s) => s.kind !== "*");
    const winner = consider(nonFallback);
    if (winner) return winner;
  }

  // 3. Universal fallback.
  const fallbacks = VISUALIZER_REGISTRY.filter((s) => s.kind === "*");
  return consider(fallbacks);
}
