/**
 * DepthMapVisualizer — false-color heatmap for ``depthmap`` payloads.
 *
 * Reads a ``DepthMap`` (float32 H×W packed as ``depth_b64``) and renders it to
 * a 2-D canvas with a configurable colormap. Range can be auto (from min/max)
 * or manually clamped via two sliders. An optional contour overlay draws iso-
 * depth lines.
 *
 * If the payload also carries a server-rendered ``image`` (DataURL), we still
 * decode the depth and render it ourselves so the colormap is interactive.
 */

import React, { useEffect, useMemo, useRef, useState } from "react";
import { b64ToF32 } from "./_lib/binary";
import { applyColormap, type ColormapName } from "./_lib/colormaps";
import { isDepthMap, type DepthMapPayload } from "./_lib/types";

export interface DepthMapVisualizerProps {
  value: unknown;
  label?: string;
}

export const DepthMapVisualizer: React.FC<DepthMapVisualizerProps> = ({ value }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [colormap, setColormap] = useState<ColormapName>("viridis");
  const [showContours, setShowContours] = useState(false);

  const decoded = useMemo(() => {
    if (!isDepthMap(value)) return null;
    const dm = value as DepthMapPayload;
    if (!dm.depth_b64 || !dm.width || !dm.height) return null;
    const depth = b64ToF32(dm.depth_b64);
    if (depth.length !== dm.width * dm.height) {
      // Some encoders pack as Float64? Fail soft; just clip.
      // We won't try to recover — the schema says Float32.
    }
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < depth.length; i++) {
      const v = depth[i];
      if (Number.isFinite(v)) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
    if (!Number.isFinite(lo)) { lo = 0; hi = 1; }
    if (hi === lo) hi = lo + 1;
    return {
      depth,
      width: dm.width,
      height: dm.height,
      autoMin: dm.min_depth ?? lo,
      autoMax: dm.max_depth ?? hi,
    };
  }, [value]);

  const [range, setRange] = useState<[number, number] | null>(null);
  // Reset range when a new map arrives.
  useEffect(() => {
    if (decoded) setRange([decoded.autoMin, decoded.autoMax]);
  }, [decoded?.depth, decoded?.autoMin, decoded?.autoMax]);

  // Render depth -> canvas using selected colormap and range.
  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !decoded || !range) return;
    cv.width = decoded.width;
    cv.height = decoded.height;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    const id = ctx.createImageData(decoded.width, decoded.height);
    const [lo, hi] = range;
    const span = hi - lo || 1;
    for (let i = 0; i < decoded.depth.length; i++) {
      const v = decoded.depth[i];
      const t = Number.isFinite(v) ? Math.max(0, Math.min(1, (v - lo) / span)) : 0;
      const [r, g, b] = applyColormap(colormap, t);
      id.data[i * 4 + 0] = (r * 255) | 0;
      id.data[i * 4 + 1] = (g * 255) | 0;
      id.data[i * 4 + 2] = (b * 255) | 0;
      id.data[i * 4 + 3] = Number.isFinite(v) ? 255 : 0;
    }
    ctx.putImageData(id, 0, 0);

    if (showContours) {
      // Simple iso-line heuristic: draw 6 evenly spaced thresholds.
      const tmp = ctx.getImageData(0, 0, cv.width, cv.height);
      const overlay = new Uint8ClampedArray(tmp.data.length);
      const W = cv.width;
      const levels = 6;
      for (let li = 1; li < levels; li++) {
        const thresh = lo + (li / levels) * span;
        for (let y = 1; y < cv.height; y++) {
          for (let x = 1; x < W; x++) {
            const a = decoded.depth[y * W + x];
            const b = decoded.depth[y * W + x - 1];
            const c = decoded.depth[(y - 1) * W + x];
            const isContour = (a - thresh) * (b - thresh) < 0 || (a - thresh) * (c - thresh) < 0;
            if (isContour) {
              const idx = (y * W + x) * 4;
              overlay[idx + 0] = 255;
              overlay[idx + 1] = 255;
              overlay[idx + 2] = 255;
              overlay[idx + 3] = 200;
            }
          }
        }
      }
      // Composite overlay.
      const merged = ctx.getImageData(0, 0, cv.width, cv.height);
      for (let i = 0; i < merged.data.length; i += 4) {
        const a = overlay[i + 3] / 255;
        if (a > 0) {
          merged.data[i] = (1 - a) * merged.data[i] + a * 255;
          merged.data[i + 1] = (1 - a) * merged.data[i + 1] + a * 255;
          merged.data[i + 2] = (1 - a) * merged.data[i + 2] + a * 255;
        }
      }
      ctx.putImageData(merged, 0, 0);
    }
  }, [decoded, colormap, range, showContours]);

  if (!decoded) {
    return (
      <div style={emptyStyle}>
        {value ? "Invalid depthmap payload" : "No depth data"}
      </div>
    );
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#0a0d12",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
        <canvas
          ref={canvasRef}
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
            imageRendering: "pixelated",
          }}
        />
      </div>

      <div
        style={{
          position: "absolute",
          top: 6,
          left: 6,
          right: 6,
          display: "flex",
          gap: 6,
          flexWrap: "wrap",
          alignItems: "center",
          padding: "4px 8px",
          background: "rgba(10, 12, 18, 0.7)",
          backdropFilter: "blur(8px)",
          border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 4,
          fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
        }}
      >
        <span style={lbl}>map</span>
        <select
          value={colormap}
          onChange={(e) => setColormap(e.target.value as ColormapName)}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          style={selectStyle}
        >
          {(["viridis", "turbo", "plasma", "magma", "grayscale"] as ColormapName[]).map((c) => (
            <option key={c} value={c}>{c}</option>
          ))}
        </select>
        <span style={lbl}>min</span>
        <input
          type="range"
          min={decoded.autoMin}
          max={decoded.autoMax}
          step={(decoded.autoMax - decoded.autoMin) / 200 || 0.01}
          value={range?.[0] ?? decoded.autoMin}
          onChange={(e) => setRange((r) => [parseFloat(e.target.value), r?.[1] ?? decoded.autoMax])}
          style={{ width: 70, accentColor: "#5da3ff" }}
        />
        <span style={lbl}>max</span>
        <input
          type="range"
          min={decoded.autoMin}
          max={decoded.autoMax}
          step={(decoded.autoMax - decoded.autoMin) / 200 || 0.01}
          value={range?.[1] ?? decoded.autoMax}
          onChange={(e) => setRange((r) => [r?.[0] ?? decoded.autoMin, parseFloat(e.target.value)])}
          style={{ width: 70, accentColor: "#5da3ff" }}
        />
        <button
          onClick={() => setRange([decoded.autoMin, decoded.autoMax])}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          style={btnStyle}
        >Reset</button>
        <button
          onClick={() => setShowContours((v) => !v)}
          onMouseDown={(e) => e.stopPropagation()}
          onPointerDown={(e) => e.stopPropagation()}
          style={{
            ...btnStyle,
            background: showContours
              ? "linear-gradient(135deg, rgba(56,128,255,0.35), rgba(80,180,255,0.25))"
              : "rgba(255,255,255,0.04)",
            color: showContours ? "#8ac4ff" : "rgba(200,200,210,0.7)",
          }}
        >Contours</button>
        <span style={{ ...lbl, marginLeft: "auto" }}>
          {decoded.width}×{decoded.height} · {(range?.[0] ?? 0).toFixed(2)}–{(range?.[1] ?? 0).toFixed(2)}
        </span>
      </div>
    </div>
  );
};

const lbl: React.CSSProperties = {
  fontSize: 10,
  color: "rgba(150,160,180,0.7)",
  letterSpacing: 0.5,
  fontFamily: "'JetBrains Mono','Fira Code',monospace",
};

const selectStyle: React.CSSProperties = {
  background: "rgba(0,0,0,0.4)",
  color: "#cfd8e8",
  border: "1px solid rgba(255,255,255,0.1)",
  borderRadius: 4,
  padding: "2px 4px",
  fontSize: 11,
  cursor: "pointer",
  outline: "none",
};

const btnStyle: React.CSSProperties = {
  background: "rgba(255,255,255,0.06)",
  color: "#cfd8e8",
  border: "1px solid rgba(255,255,255,0.08)",
  borderRadius: 4,
  padding: "2px 8px",
  fontSize: 11,
  fontWeight: 600,
  cursor: "pointer",
};

const emptyStyle: React.CSSProperties = {
  width: "100%",
  height: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  color: "rgba(170,180,200,0.55)",
  fontSize: 12,
  fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
  background: "#0a0d12",
};

export default DepthMapVisualizer;
