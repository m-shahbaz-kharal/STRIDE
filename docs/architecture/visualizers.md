# Visualizers

The visualizer registry maps a port's `kind` (and optional
`metadata.subtype`) to a React component the dashboard renders for that
output. Every node spec contributes a *port type*, not a *widget* — the
registry is the single point of truth that picks the widget.

## How dispatch works

When the dashboard renders a published port, it calls
`resolveVisualizer(typeDescriptor, hints)` and falls back through this
ordering until one matches:

1. Exact `(kind, subtype)` match.
2. Exact `kind` match (no subtype).
3. The container-element type, recursively (e.g. `list<image>` falls to
   `image` plus a "list of N" wrapper).
4. The hard-coded "JSON dump" widget for unhandled kinds.

The registry itself lives at
`frontend/src/visualizers/index.ts` and is currently populated by
hand. Each entry declares:

```ts
interface VisualizerSpec {
  kind: string;
  subtype?: string;                 // narrower match wins
  priority?: number;                // tiebreak; higher = preferred
  component: React.ComponentType<{
    value: unknown;
    descriptor: TypeDescriptor;
  }>;
}
```

## Default inventory

Phase 5 ships these built-in visualizers:

| Kind | Component | Notes |
|---|---|---|
| `image` | `ImageWidget` | Renders the data URL inline; respects `format`. |
| `detections2d` | `Detections2DOverlay` | Composites bbox2d boxes onto the bundled `image`. |
| `pointcloud` / `scene3d` | `Scene3DWidget` | Three.js + drei viewer; lazy-loaded. |
| `depthmap` | `DepthMapWidget` | Reuses the colorized `image` field. |
| `keypoints` | `KeypointsOverlay` | Skeleton overlay on the bundled image. |
| primitive scalars | `ValuePopup` | Number / string / boolean inspector. |

## Plugin-contributed visualizers

A plugin package can ship its own visualizer by exporting a
`stride.visualizer.json` manifest at the package root. The manifest
points at one or more entry components:

```json
{
  "version": 1,
  "visualizers": [
    {
      "kind": "stride.foo.frame",
      "subtype": "thermal",
      "module": "./visualizers/ThermalFrame.tsx",
      "priority": 100
    }
  ]
}
```

A future Vite plugin will scan installed plugin packages at frontend
build time, generate dynamic imports for each manifest entry, and merge
them into the registry. The plugin is **not yet implemented** in
Phase 5 — it's the next obvious extension and is tracked as a follow-up
task. Until it ships, plugin packages must add their visualizers
directly to `frontend/src/visualizers/index.ts` (manual registration);
`Scene3DWidget` is the example to follow.

## Composition / overlays

Some widgets consume more than one record: `Detections2DOverlay`
composites a `bbox2d[]` over the `image` carried inside the
`detections2d` record itself. The pattern is:

1. The visualizer receives the *outer* record (`detections2d`).
2. It pulls the inner `image` (`record.image`) and renders it.
3. It walks `record.boxes` and overlays each bbox.

This is why every domain record carries its source `image` (or
equivalent) — the visualizer can render without a separate "render this
image" upstream node.

## Performance envelope

- Pointclouds > 200k points are streamed to a Web Worker that decodes
  the base64 buffer to a `Float32Array` off the main thread. The
  current Scene3DWidget decodes synchronously; a Worker migration is
  tracked as Phase-N+1 work.
- Image widgets reuse a single `<img>` element across re-renders
  (React reconciliation) so successive frames don't trigger a layout
  thrash.
- The dashboard uses React.memo on every widget; widgets receive a
  stable `value` reference (the executor reuses the dict if cached) so
  unchanged values bypass render entirely.

## See also

- [Type System](./type-system.md) — the kinds and subtypes the registry dispatches on.
- [Unified design doc](./unified-type-system-and-ux.md) §8 — the full visualizer registry design.
