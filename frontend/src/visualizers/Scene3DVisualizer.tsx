/**
 * Scene3DVisualizer — the powerful 3D viewer.
 *
 * A single ``@react-three/fiber`` viewer for every 3-D wire payload. Supports:
 *
 *   - Orbit / pan / zoom controls (drei ``<OrbitControls />``).
 *   - Point cloud rendering via a custom shader material with selectable
 *     colormap (viridis / turbo / grayscale / height / solid) and
 *     adjustable point size. Auto-fit camera to cloud bounds.
 *   - 3-D bounding box overlay (wireframe boxes, color-coded by class id or
 *     track id, with optional floating label sprites).
 *   - Track trails: when a payload carries a ``Track3D`` history field the
 *     recent positions are rendered as a fading polyline.
 *   - Region overlays: dashed wireframe + low-alpha translucent fill so they
 *     visually distinguish from detection boxes.
 *   - Coordinate axes gizmo (drei ``<GizmoHelper />``).
 *   - Toggleable ground plane grid (drei ``<Grid />``).
 *   - HUD overlays: live point count, FPS, current camera position.
 *   - Composition: accepts both a "primary" payload (point cloud / scene) and
 *     overlay payloads (detections3d / track3d arrays / bbox3d list / regions).
 *   - Performance: large clouds (>500k points) auto-downsample for rendering.
 *
 * Reference: docs/architecture/unified-type-system-and-ux.md §8 (visualizer
 * registry) and §8.5 (performance envelope — three.js scenes share a single
 * WebGL context per dashboard).
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import {
  OrbitControls,
  Grid,
  GizmoHelper,
  GizmoViewport,
  Html,
  Line,
} from "@react-three/drei";
import * as THREE from "three";
import { b64ToF32 } from "./_lib/binary";
import { COLORMAPS, type ColormapName, colorFromId, rgbaToCss } from "./_lib/colormaps";
import {
  isBBox3D,
  isDetections3D,
  isPointCloud,
  isRegion3D,
  isScene3D,
  isTrack3D,
  type BBox3DPayload,
  type PointCloudPayload,
  type Region3DPayload,
  type Scene3DPayload,
  type Track3DPayload,
} from "./_lib/types";

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

export interface Scene3DVisualizerProps {
  /**
   * Primary payload. Can be a ``PointCloud``, a ``Scene3D``, or undefined
   * (in which case the scene is empty unless ``overlays`` provides one).
   */
  value: unknown;
  /** Composition overlays — additional 3-D payloads (boxes, tracks, regions). */
  overlays?: unknown[];
  /** Optional widget label (currently unused in the visualizer body). */
  label?: string;
}

/** Resolution thresholds for big-cloud downsampling. */
const DOWNSAMPLE_THRESHOLD = 500_000;
const DOWNSAMPLE_TARGET = 400_000;

// ---------------------------------------------------------------------------
// Decoded payload shapes (post-base64 expansion)
// ---------------------------------------------------------------------------

interface DecodedCloud {
  positions: Float32Array; // [x,y,z,...]
  count: number; // num points actually rendered (after downsample)
  origCount: number;
  fieldNames: string[];
  fieldArrays: Record<string, Float32Array>;
  bounds: { min: THREE.Vector3; max: THREE.Vector3; center: THREE.Vector3; radius: number };
}

interface DecodedScene {
  cloud: DecodedCloud | null;
  boxes: BBox3DPayload[];
  regions: Region3DPayload[];
  tracks: Track3DPayload[];
  occupancy: number[];
}

// ---------------------------------------------------------------------------
// Decode helpers
// ---------------------------------------------------------------------------

function decodeCloud(p: PointCloudPayload | null | undefined): DecodedCloud | null {
  if (!p) return null;
  const N = p.num_points | 0;
  if (!N) return null;

  let positions: Float32Array;
  if (p.positions_b64) {
    positions = b64ToF32(p.positions_b64);
  } else if (p.positions && p.positions.length) {
    positions = new Float32Array(N * 3);
    for (let i = 0; i < N; i++) {
      const t = p.positions[i];
      positions[i * 3] = t[0];
      positions[i * 3 + 1] = t[1];
      positions[i * 3 + 2] = t[2];
    }
  } else {
    return null;
  }

  // Decode fields.
  const fieldArrays: Record<string, Float32Array> = {};
  if (p.fields_b64) {
    for (const [k, v] of Object.entries(p.fields_b64)) fieldArrays[k] = b64ToF32(v);
  } else if (p.fields) {
    for (const [k, a] of Object.entries(p.fields)) fieldArrays[k] = new Float32Array(a);
  }

  // Optional downsample for huge clouds.
  let outCount = N;
  let outPositions = positions;
  let outFields = fieldArrays;
  if (N > DOWNSAMPLE_THRESHOLD) {
    const stride = Math.ceil(N / DOWNSAMPLE_TARGET);
    outCount = Math.floor(N / stride);
    outPositions = new Float32Array(outCount * 3);
    for (let i = 0; i < outCount; i++) {
      const j = i * stride;
      outPositions[i * 3] = positions[j * 3];
      outPositions[i * 3 + 1] = positions[j * 3 + 1];
      outPositions[i * 3 + 2] = positions[j * 3 + 2];
    }
    outFields = {};
    for (const [k, arr] of Object.entries(fieldArrays)) {
      const ds = new Float32Array(outCount);
      for (let i = 0; i < outCount; i++) ds[i] = arr[i * stride];
      outFields[k] = ds;
    }
  }

  // Bounds.
  let x0 = Infinity, y0 = Infinity, z0 = Infinity;
  let x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
  for (let i = 0; i < outCount; i++) {
    const x = outPositions[i * 3];
    const y = outPositions[i * 3 + 1];
    const z = outPositions[i * 3 + 2];
    if (x < x0) x0 = x; if (x > x1) x1 = x;
    if (y < y0) y0 = y; if (y > y1) y1 = y;
    if (z < z0) z0 = z; if (z > z1) z1 = z;
  }
  if (!Number.isFinite(x0)) {
    x0 = -1; y0 = -1; z0 = -1; x1 = 1; y1 = 1; z1 = 1;
  }
  const min = new THREE.Vector3(x0, y0, z0);
  const max = new THREE.Vector3(x1, y1, z1);
  const center = new THREE.Vector3().addVectors(min, max).multiplyScalar(0.5);
  const size = new THREE.Vector3().subVectors(max, min);
  const radius = Math.max(size.x, size.y, size.z, 1) * 0.5;

  return {
    positions: outPositions,
    count: outCount,
    origCount: N,
    fieldNames: Object.keys(outFields),
    fieldArrays: outFields,
    bounds: { min, max, center, radius },
  };
}

function isPointCloudLike(v: unknown): v is PointCloudPayload {
  return isPointCloud(v);
}

function decodeOverlays(value: unknown, overlays: unknown[] | undefined): DecodedScene {
  const result: DecodedScene = {
    cloud: null,
    boxes: [],
    regions: [],
    tracks: [],
    occupancy: [],
  };

  const consume = (v: unknown) => {
    if (!v) return;
    if (isScene3D(v)) {
      const s = v as Scene3DPayload;
      if (!result.cloud && s.point_cloud) result.cloud = decodeCloud(s.point_cloud);
      if (s.boxes) result.boxes.push(...s.boxes);
      if (s.regions) result.regions.push(...s.regions);
      if (s.occupancy) result.occupancy = s.occupancy;
      return;
    }
    if (isPointCloudLike(v)) {
      if (!result.cloud) result.cloud = decodeCloud(v);
      return;
    }
    if (isDetections3D(v)) {
      result.boxes.push(...(v.boxes || []));
      return;
    }
    if (Array.isArray(v)) {
      for (const item of v) consume(item);
      return;
    }
    if (isTrack3D(v)) {
      result.tracks.push(v);
      return;
    }
    if (isRegion3D(v)) {
      result.regions.push(v);
      return;
    }
    if (isBBox3D(v)) {
      result.boxes.push(v);
      return;
    }
  };

  consume(value);
  if (overlays) for (const o of overlays) consume(o);
  return result;
}

// ---------------------------------------------------------------------------
// Custom point shader — colormap on the GPU
// ---------------------------------------------------------------------------

const POINT_VERT = /* glsl */ `
  attribute float aField;
  attribute float aHeight;
  uniform float uPointSize;
  uniform float uMin;
  uniform float uMax;
  uniform int uMode;       // 0=field 1=height 2=solid
  varying float vT;
  varying float vSolid;
  void main() {
    vec4 mv = modelViewMatrix * vec4(position, 1.0);
    gl_Position = projectionMatrix * mv;
    gl_PointSize = uPointSize * (300.0 / -mv.z);
    float val = uMode == 1 ? aHeight : aField;
    float t = (val - uMin) / max(uMax - uMin, 0.0001);
    vT = clamp(t, 0.0, 1.0);
    vSolid = uMode == 2 ? 1.0 : 0.0;
  }
`;

// Polynomial fits for turbo / viridis / grayscale; selectable via uniform.
const POINT_FRAG = /* glsl */ `
  precision mediump float;
  uniform int uColormap; // 0=viridis 1=turbo 2=grayscale
  uniform vec3 uSolidColor;
  varying float vT;
  varying float vSolid;

  vec3 turboMap(float t) {
    float r = 0.13572+t*(4.6153+t*(-42.66+t*(132.13+t*(-152.95+t*56.67))));
    float g = 0.09140+t*(2.1643+t*(4.8428+t*(-27.66+t*(29.04+t*(-8.36)))));
    float b = 0.10667+t*(12.486+t*(-60.46+t*(109.98+t*(-89.09+t*25.79))));
    return clamp(vec3(r,g,b), 0.0, 1.0);
  }
  vec3 viridisMap(float t) {
    float r = 0.2777273 + t * (-0.1058086 + t * (-2.951 + t * (10.0 + t * (-13.6 + t * 6.34))));
    float g = -0.00204 + t * (1.8 + t * (-1.55 + t * (0.8 + t * (-0.4 + t * 0.05))));
    float b = 0.329 + t * (1.84 + t * (-7.66 + t * (12.83 + t * (-9.11 + t * 2.36))));
    return clamp(vec3(r,g,b), 0.0, 1.0);
  }
  void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c,c) > 0.25) discard;
    vec3 col;
    if (vSolid > 0.5) {
      col = uSolidColor;
    } else if (uColormap == 1) {
      col = turboMap(vT);
    } else if (uColormap == 2) {
      col = vec3(vT, vT, vT);
    } else {
      col = viridisMap(vT);
    }
    gl_FragColor = vec4(col, 1.0);
  }
`;

// ---------------------------------------------------------------------------
// Subcomponents
// ---------------------------------------------------------------------------

interface PointCloudMeshProps {
  cloud: DecodedCloud;
  pointSize: number;
  colorField: string; // "height" | "_solid" | actual field name
  colormap: ColormapName;
}

const PointCloudMesh: React.FC<PointCloudMeshProps> = ({ cloud, pointSize, colorField, colormap }) => {
  const ref = useRef<THREE.Points>(null);

  // Build geometry once per cloud (positions + height attribute).
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.BufferAttribute(cloud.positions, 3));
    const heights = new Float32Array(cloud.count);
    for (let i = 0; i < cloud.count; i++) heights[i] = cloud.positions[i * 3 + 2];
    g.setAttribute("aHeight", new THREE.BufferAttribute(heights, 1));
    return g;
  }, [cloud]);

  // Active field as a separate attribute (swappable without re-creating geometry).
  useEffect(() => {
    const active =
      colorField !== "_solid" && colorField !== "height" && cloud.fieldArrays[colorField]
        ? cloud.fieldArrays[colorField]
        : new Float32Array(cloud.count);
    geometry.setAttribute("aField", new THREE.BufferAttribute(active, 1));
    geometry.attributes.aField.needsUpdate = true;
  }, [geometry, cloud, colorField]);

  // Range uniforms.
  const [uMin, uMax] = useMemo(() => {
    if (colorField === "_solid") return [0, 1];
    const arr =
      colorField !== "height" && cloud.fieldArrays[colorField]
        ? cloud.fieldArrays[colorField]
        : null;
    if (arr) {
      let lo = Infinity, hi = -Infinity;
      for (let i = 0; i < arr.length; i++) {
        if (arr[i] < lo) lo = arr[i];
        if (arr[i] > hi) hi = arr[i];
      }
      if (hi === lo) hi = lo + 1;
      return [lo, hi];
    }
    // Height range from bounds.
    return [cloud.bounds.min.z, cloud.bounds.max.z === cloud.bounds.min.z ? cloud.bounds.min.z + 1 : cloud.bounds.max.z];
  }, [cloud, colorField]);

  const material = useMemo(() => {
    const m = new THREE.ShaderMaterial({
      vertexShader: POINT_VERT,
      fragmentShader: POINT_FRAG,
      uniforms: {
        uPointSize: { value: pointSize },
        uMin: { value: uMin },
        uMax: { value: uMax },
        uMode: { value: colorField === "_solid" ? 2 : colorField === "height" ? 1 : 0 },
        uColormap: { value: colormap === "viridis" ? 0 : colormap === "turbo" ? 1 : 2 },
        uSolidColor: { value: new THREE.Vector3(0.25, 0.72, 1.0) },
      },
      transparent: false,
      depthTest: true,
    });
    return m;
  }, []); // Material instance is stable; we update uniforms below.

  useEffect(() => {
    material.uniforms.uPointSize.value = pointSize;
    material.uniforms.uMin.value = uMin;
    material.uniforms.uMax.value = uMax;
    material.uniforms.uMode.value =
      colorField === "_solid" ? 2 : colorField === "height" ? 1 : 0;
    material.uniforms.uColormap.value =
      colormap === "viridis" ? 0 : colormap === "turbo" ? 1 : 2;
  }, [material, pointSize, uMin, uMax, colorField, colormap]);

  return <points ref={ref} geometry={geometry} material={material} />;
};

interface BoxOverlayProps {
  box: BBox3DPayload;
  color: [number, number, number];
  showLabel: boolean;
  labelText?: string;
  dashed?: boolean;
  fillAlpha?: number;
}

const BoxOverlay: React.FC<BoxOverlayProps> = ({ box, color, showLabel, labelText, dashed, fillAlpha }) => {
  const [cx, cy, cz] = box.center;
  const [sx, sy, sz] = box.size;
  const colorObj = useMemo(() => new THREE.Color(color[0], color[1], color[2]), [color]);

  // 12 edges of an AABB built from center+size. Drei's <Line/> takes a points array.
  const points = useMemo<THREE.Vector3[]>(() => {
    const hx = sx / 2, hy = sy / 2, hz = sz / 2;
    const c = (dx: number, dy: number, dz: number) =>
      new THREE.Vector3(cx + dx * hx, cy + dy * hy, cz + dz * hz);
    const corners = [
      c(-1, -1, -1), c(1, -1, -1), c(1, 1, -1), c(-1, 1, -1),
      c(-1, -1, 1),  c(1, -1, 1),  c(1, 1, 1),  c(-1, 1, 1),
    ];
    const edges: [number, number][] = [
      [0, 1], [1, 2], [2, 3], [3, 0],
      [4, 5], [5, 6], [6, 7], [7, 4],
      [0, 4], [1, 5], [2, 6], [3, 7],
    ];
    const pts: THREE.Vector3[] = [];
    for (const [a, b] of edges) {
      pts.push(corners[a], corners[b]);
    }
    return pts;
  }, [cx, cy, cz, sx, sy, sz]);

  return (
    <group>
      <Line
        points={points}
        color={colorObj}
        lineWidth={dashed ? 1.5 : 2}
        dashed={dashed}
        dashSize={0.15}
        gapSize={0.1}
        segments
      />
      {fillAlpha !== undefined && fillAlpha > 0 && (
        <mesh position={[cx, cy, cz]}>
          <boxGeometry args={[sx, sy, sz]} />
          <meshBasicMaterial color={colorObj} transparent opacity={fillAlpha} depthWrite={false} />
        </mesh>
      )}
      {showLabel && labelText && (
        <Html
          position={[cx, cy, cz + sz / 2 + 0.2]}
          center
          distanceFactor={10}
          style={{ pointerEvents: "none" }}
        >
          <div
            style={{
              background: "rgba(0,0,0,0.65)",
              color: rgbaToCss(color, 1),
              border: `1px solid ${rgbaToCss(color, 0.8)}`,
              padding: "2px 6px",
              borderRadius: 4,
              fontSize: 11,
              fontWeight: 600,
              fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
              whiteSpace: "nowrap",
              textShadow: "0 0 3px rgba(0,0,0,0.8)",
            }}
          >
            {labelText}
          </div>
        </Html>
      )}
    </group>
  );
};

interface TrackTrailProps {
  track: Track3DPayload;
  color: [number, number, number];
}

const TrackTrail: React.FC<TrackTrailProps> = ({ track, color }) => {
  const colorObj = useMemo(() => new THREE.Color(color[0], color[1], color[2]), [color]);
  const points = useMemo(() => {
    const hist = (track.history && track.history.length > 0)
      ? track.history
      : [track.center];
    return hist.map((c) => new THREE.Vector3(c[0], c[1], c[2]));
  }, [track]);
  if (points.length < 2) return null;
  return <Line points={points} color={colorObj} lineWidth={2} transparent opacity={0.6} />;
};

// ---------------------------------------------------------------------------
// Camera auto-fit
// ---------------------------------------------------------------------------

const CameraAutoFit: React.FC<{ bounds: DecodedCloud["bounds"] | null; trigger: number }> = ({
  bounds,
  trigger,
}) => {
  const { camera } = useThree();
  useEffect(() => {
    if (!bounds) return;
    const r = bounds.radius;
    const target = bounds.center;
    const offset = new THREE.Vector3(r * 1.6, -r * 1.6, r * 1.6);
    camera.position.copy(target).add(offset);
    camera.up.set(0, 0, 1);
    camera.lookAt(target);
    if ((camera as THREE.PerspectiveCamera).isPerspectiveCamera) {
      (camera as THREE.PerspectiveCamera).near = Math.max(0.01, r * 0.001);
      (camera as THREE.PerspectiveCamera).far = Math.max(1000, r * 100);
      (camera as THREE.PerspectiveCamera).updateProjectionMatrix();
    }
  }, [bounds, trigger, camera]);
  return null;
};

// ---------------------------------------------------------------------------
// FPS / camera HUD reporter
// ---------------------------------------------------------------------------

interface HUDReporterProps {
  onUpdate: (info: { fps: number; pos: [number, number, number] }) => void;
}
const HUDReporter: React.FC<HUDReporterProps> = ({ onUpdate }) => {
  const { camera } = useThree();
  const lastReport = useRef(performance.now());
  const frames = useRef(0);
  useFrame(() => {
    frames.current++;
    const now = performance.now();
    if (now - lastReport.current >= 500) {
      const fps = (frames.current * 1000) / (now - lastReport.current);
      frames.current = 0;
      lastReport.current = now;
      onUpdate({
        fps: Math.round(fps),
        pos: [camera.position.x, camera.position.y, camera.position.z],
      });
    }
  });
  return null;
};

// ---------------------------------------------------------------------------
// Main visualizer
// ---------------------------------------------------------------------------

export const Scene3DVisualizer: React.FC<Scene3DVisualizerProps> = ({ value, overlays }) => {
  const decoded = useMemo(() => decodeOverlays(value, overlays), [value, overlays]);

  const [pointSize, setPointSize] = useState(2.5);
  const [colormap, setColormap] = useState<ColormapName>("viridis");
  const [colorField, setColorField] = useState<string>("height");
  const [showGrid, setShowGrid] = useState(true);
  const [showBoxes, setShowBoxes] = useState(true);
  const [showRegions, setShowRegions] = useState(true);
  const [showLabels, setShowLabels] = useState(true);
  const [showHud, setShowHud] = useState(true);
  const [fitTick, setFitTick] = useState(0);
  const [hud, setHud] = useState<{ fps: number; pos: [number, number, number] }>({
    fps: 0,
    pos: [0, 0, 0],
  });

  // When the cloud changes (different num_points) trigger a fit.
  const cloudKey = decoded.cloud
    ? `${decoded.cloud.origCount}-${decoded.cloud.bounds.center.x.toFixed(2)}-${decoded.cloud.bounds.center.y.toFixed(2)}`
    : "empty";
  useEffect(() => {
    setFitTick((t) => t + 1);
  }, [cloudKey]);

  // Reset color field when fields list changes.
  useEffect(() => {
    if (decoded.cloud && colorField !== "_solid" && colorField !== "height") {
      if (!decoded.cloud.fieldArrays[colorField]) setColorField("height");
    }
  }, [decoded.cloud, colorField]);

  const cloud = decoded.cloud;

  const fieldOptions = useMemo(() => {
    const opts: { v: string; l: string }[] = [{ v: "height", l: "Height (Z)" }];
    if (cloud) {
      for (const k of cloud.fieldNames) {
        opts.push({ v: k, l: k.charAt(0).toUpperCase() + k.slice(1) });
      }
    }
    opts.push({ v: "_solid", l: "Solid" });
    return opts;
  }, [cloud]);

  // Empty state.
  const empty = !cloud && decoded.boxes.length === 0 && decoded.regions.length === 0 && decoded.tracks.length === 0;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "linear-gradient(180deg, #0d1018 0%, #08090e 100%)",
        borderRadius: 4,
        overflow: "hidden",
      }}
    >
      <Canvas
        camera={{ position: [10, -10, 10], fov: 45, up: [0, 0, 1] }}
        gl={{ antialias: true, alpha: false, preserveDrawingBuffer: false }}
        style={{ position: "absolute", inset: 0 }}
      >
        <color attach="background" args={[0.04, 0.05, 0.07]} />
        <ambientLight intensity={0.6} />
        <directionalLight position={[10, 10, 10]} intensity={0.4} />

        {showGrid && (
          <Grid
            args={[40, 40]}
            cellSize={1}
            cellThickness={0.5}
            cellColor="#2a3142"
            sectionSize={5}
            sectionThickness={1}
            sectionColor="#3a4a6e"
            fadeDistance={80}
            fadeStrength={1}
            infiniteGrid
            position={[0, 0, cloud ? cloud.bounds.min.z : 0]}
            rotation={[Math.PI / 2, 0, 0]}
          />
        )}

        {cloud && (
          <PointCloudMesh
            cloud={cloud}
            pointSize={pointSize}
            colorField={colorField}
            colormap={colormap}
          />
        )}

        {showBoxes &&
          decoded.boxes.map((b, i) => {
            const idForColor = b.id ?? b.class_id ?? i;
            const color = colorFromId(idForColor);
            const labelParts: string[] = [];
            if (b.id !== undefined && b.id !== null) labelParts.push(`#${b.id}`);
            if (b.class_name) labelParts.push(b.class_name);
            if (b.confidence !== undefined && b.confidence !== null) {
              labelParts.push(`${Math.round(b.confidence * 100)}%`);
            }
            return (
              <BoxOverlay
                key={`box-${i}`}
                box={b}
                color={color}
                showLabel={showLabels}
                labelText={labelParts.join(" ") || `Box ${i + 1}`}
              />
            );
          })}

        {showBoxes &&
          decoded.tracks.map((t, i) => {
            const color = colorFromId(t.id);
            const labelParts: string[] = [`Track #${t.id}`];
            if (t.class_name) labelParts.push(t.class_name);
            return (
              <React.Fragment key={`track-${t.id}-${i}`}>
                <BoxOverlay
                  box={t}
                  color={color}
                  showLabel={showLabels}
                  labelText={labelParts.join(" ")}
                />
                <TrackTrail track={t} color={color} />
              </React.Fragment>
            );
          })}

        {showRegions &&
          decoded.regions.map((r, i) => {
            const color: [number, number, number] = [0.25, 0.7, 0.95];
            return (
              <BoxOverlay
                key={`region-${i}-${r.name}`}
                box={r as unknown as BBox3DPayload}
                color={color}
                showLabel={showLabels}
                labelText={r.name}
                dashed
                fillAlpha={0.08}
              />
            );
          })}

        <OrbitControls
          makeDefault
          target={cloud ? [cloud.bounds.center.x, cloud.bounds.center.y, cloud.bounds.center.z] : [0, 0, 0]}
          enableDamping
          dampingFactor={0.08}
        />
        <CameraAutoFit bounds={cloud?.bounds ?? null} trigger={fitTick} />
        <GizmoHelper alignment="bottom-right" margin={[60, 60]}>
          <GizmoViewport
            axisColors={["#ff5d5d", "#5dff7e", "#5da3ff"]}
            labelColor="white"
          />
        </GizmoHelper>
        <HUDReporter onUpdate={setHud} />
      </Canvas>

      {/* HUD / control overlay */}
      <div
        style={{
          position: "absolute",
          inset: 0,
          pointerEvents: "none",
          padding: 8,
          display: "flex",
          flexDirection: "column",
          justifyContent: "space-between",
          fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
        }}
      >
        {/* Top row */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 6 }}>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            <Panel>
              <Label>Color</Label>
              <Select value={colorField} onChange={(e) => setColorField(e.target.value)}>
                {fieldOptions.map((o) => (
                  <option key={o.v} value={o.v}>{o.l}</option>
                ))}
              </Select>
            </Panel>
            <Panel>
              <Label>Map</Label>
              <Select value={colormap} onChange={(e) => setColormap(e.target.value as ColormapName)}>
                {(["viridis", "turbo", "grayscale"] as ColormapName[]).map((c) => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </Select>
            </Panel>
            <Panel>
              <Label>Size</Label>
              <input
                type="range"
                min={0.5}
                max={8}
                step={0.5}
                value={pointSize}
                onChange={(e) => setPointSize(parseFloat(e.target.value))}
                style={{ pointerEvents: "auto", width: 80, accentColor: "#5da3ff" }}
              />
              <span style={{ color: "#7c8ba8", fontSize: 10, minWidth: 22, textAlign: "right" }}>
                {pointSize.toFixed(1)}
              </span>
            </Panel>
          </div>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            <Panel>
              <Toggle on={showGrid} onClick={() => setShowGrid((v) => !v)} title="Toggle grid">Grid</Toggle>
              <Toggle on={showBoxes} onClick={() => setShowBoxes((v) => !v)} title="Toggle boxes">Boxes</Toggle>
              <Toggle on={showRegions} onClick={() => setShowRegions((v) => !v)} title="Toggle regions">Regions</Toggle>
              <Toggle on={showLabels} onClick={() => setShowLabels((v) => !v)} title="Toggle labels">Labels</Toggle>
            </Panel>
            <Panel>
              <Btn onClick={() => setFitTick((t) => t + 1)} title="Auto-fit camera to data">Fit</Btn>
              <Toggle on={showHud} onClick={() => setShowHud((v) => !v)} title="Toggle HUD">HUD</Toggle>
            </Panel>
          </div>
        </div>

        {/* Bottom row HUD */}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
          {showHud && (
            <Panel>
              <span style={hudText}>
                {cloud
                  ? `${cloud.count.toLocaleString()} pts${cloud.origCount !== cloud.count ? ` (of ${cloud.origCount.toLocaleString()})` : ""}`
                  : "no cloud"}
              </span>
              {decoded.boxes.length + decoded.tracks.length > 0 && (
                <span style={hudText}>
                  {decoded.boxes.length + decoded.tracks.length} box
                  {decoded.boxes.length + decoded.tracks.length === 1 ? "" : "es"}
                </span>
              )}
              {decoded.regions.length > 0 && (
                <span style={hudText}>{decoded.regions.length} region{decoded.regions.length === 1 ? "" : "s"}</span>
              )}
            </Panel>
          )}
          {showHud && (
            <Panel>
              <span style={hudText}>{hud.fps} fps</span>
              <span style={hudText}>
                cam ({hud.pos[0].toFixed(1)}, {hud.pos[1].toFixed(1)}, {hud.pos[2].toFixed(1)})
              </span>
            </Panel>
          )}
        </div>
      </div>

      {empty && (
        <div
          style={{
            position: "absolute",
            inset: 0,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            pointerEvents: "none",
            color: "rgba(170,180,200,0.55)",
            fontSize: 13,
            fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
            letterSpacing: 0.5,
          }}
        >
          Awaiting 3-D data…
        </div>
      )}
    </div>
  );
};

// ---------------------------------------------------------------------------
// Tiny UI primitives (HUD)
// ---------------------------------------------------------------------------

const hudText: React.CSSProperties = {
  fontSize: 10,
  color: "#7c8ba8",
  fontFamily: "'JetBrains Mono','Fira Code',monospace",
  whiteSpace: "nowrap",
};

const Panel: React.FC<React.PropsWithChildren> = ({ children }) => (
  <div
    style={{
      display: "flex",
      alignItems: "center",
      gap: 6,
      padding: "4px 8px",
      background: "rgba(10, 12, 18, 0.7)",
      backdropFilter: "blur(10px) saturate(1.4)",
      WebkitBackdropFilter: "blur(10px) saturate(1.4)",
      border: "1px solid rgba(255,255,255,0.06)",
      borderRadius: 6,
      pointerEvents: "auto",
    }}
  >
    {children}
  </div>
);

const Label: React.FC<React.PropsWithChildren> = ({ children }) => (
  <span style={{ fontSize: 10, color: "rgba(150,160,180,0.7)", letterSpacing: 0.5 }}>{children}</span>
);

const Select: React.FC<React.SelectHTMLAttributes<HTMLSelectElement>> = (props) => (
  <select
    {...props}
    onMouseDown={(e) => e.stopPropagation()}
    onPointerDown={(e) => e.stopPropagation()}
    style={{
      background: "rgba(0,0,0,0.4)",
      color: "#cfd8e8",
      border: "1px solid rgba(255,255,255,0.1)",
      borderRadius: 4,
      padding: "3px 6px",
      fontSize: 11,
      cursor: "pointer",
      outline: "none",
      pointerEvents: "auto",
      ...props.style,
    }}
  />
);

interface BtnProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}
const Btn: React.FC<BtnProps> = ({ style, ...rest }) => (
  <button
    {...rest}
    onMouseDown={(e) => e.stopPropagation()}
    onPointerDown={(e) => e.stopPropagation()}
    style={{
      background: "rgba(255,255,255,0.06)",
      color: "#cfd8e8",
      border: "1px solid rgba(255,255,255,0.08)",
      borderRadius: 4,
      padding: "3px 8px",
      fontSize: 11,
      fontWeight: 600,
      cursor: "pointer",
      pointerEvents: "auto",
      ...style,
    }}
  />
);

interface ToggleProps extends BtnProps {
  on: boolean;
}
const Toggle: React.FC<ToggleProps> = ({ on, children, style, ...rest }) => (
  <Btn
    {...rest}
    style={{
      background: on
        ? "linear-gradient(135deg, rgba(56,128,255,0.35), rgba(80,180,255,0.25))"
        : "rgba(255,255,255,0.04)",
      border: on ? "1px solid rgba(80,160,255,0.5)" : "1px solid rgba(255,255,255,0.06)",
      color: on ? "#8ac4ff" : "rgba(200,200,210,0.7)",
      boxShadow: on ? "0 0 6px rgba(56,128,255,0.25)" : "none",
      ...style,
    }}
  >
    {children}
  </Btn>
);

export default Scene3DVisualizer;
