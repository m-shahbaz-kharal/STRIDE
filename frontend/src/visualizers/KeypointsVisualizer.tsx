/**
 * KeypointsVisualizer — skeleton-only render when no image is bound.
 *
 * If an image is part of the same composition (or embedded in the keypoints
 * payload alongside detections), the registry routes through
 * ``ImageVisualizer`` for full overlay. This component is the standalone
 * fallback: it draws the skeleton on a blank canvas, scaled to the largest
 * keypoint extent, so the user can still see the pose graph.
 */

import React, { useEffect, useMemo, useRef } from "react";
import { ImageVisualizer } from "./ImageVisualizer";
import { colorFromId, rgbaToCss } from "./_lib/colormaps";
import { COCO17_SKELETON, isImageString, isKeypoints, type KeypointsPayload } from "./_lib/types";

export interface KeypointsVisualizerProps {
  value: unknown;
  overlays?: unknown[];
  label?: string;
}

export const KeypointsVisualizer: React.FC<KeypointsVisualizerProps> = ({ value, overlays }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  // If overlays or value contain an image, defer to ImageVisualizer.
  const imgFromOverlays = (overlays || []).find(isImageString);
  if (imgFromOverlays) {
    return <ImageVisualizer value={imgFromOverlays} overlays={[value, ...(overlays || []).filter((o) => o !== imgFromOverlays)]} />;
  }

  const kp = isKeypoints(value) ? (value as KeypointsPayload) : null;

  // Compute extents.
  const extents = useMemo(() => {
    if (!kp || !kp.instances.length) return null;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const ins of kp.instances) {
      for (const k of ins.keypoints) {
        if ((k[2] ?? 1) < 0.1) continue;
        if (k[0] < x0) x0 = k[0]; if (k[0] > x1) x1 = k[0];
        if (k[1] < y0) y0 = k[1]; if (k[1] > y1) y1 = k[1];
      }
    }
    if (!Number.isFinite(x0)) return null;
    const margin = Math.max(20, (x1 - x0) * 0.1);
    return { x0: x0 - margin, y0: y0 - margin, x1: x1 + margin, y1: y1 + margin };
  }, [kp]);

  useEffect(() => {
    const cv = canvasRef.current;
    if (!cv || !kp || !extents) return;
    const W = 600;
    const H = Math.max(200, Math.round(W * (extents.y1 - extents.y0) / Math.max(1, extents.x1 - extents.x0)));
    cv.width = W;
    cv.height = H;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "#11141a";
    ctx.fillRect(0, 0, W, H);

    const sx = W / (extents.x1 - extents.x0);
    const sy = H / (extents.y1 - extents.y0);
    const tx = (x: number) => (x - extents.x0) * sx;
    const ty = (y: number) => (y - extents.y0) * sy;

    const skel = (kp.skeleton && kp.skeleton.length ? kp.skeleton : COCO17_SKELETON);

    for (let inst = 0; inst < kp.instances.length; inst++) {
      const ins = kp.instances[inst];
      const c = colorFromId(inst);
      ctx.strokeStyle = rgbaToCss(c, 0.95);
      ctx.lineWidth = 2.5;
      for (const [a, b] of skel) {
        const ka = ins.keypoints[a];
        const kb = ins.keypoints[b];
        if (!ka || !kb) continue;
        if ((ka[2] ?? 1) < 0.1 || (kb[2] ?? 1) < 0.1) continue;
        ctx.beginPath();
        ctx.moveTo(tx(ka[0]), ty(ka[1]));
        ctx.lineTo(tx(kb[0]), ty(kb[1]));
        ctx.stroke();
      }
      ctx.fillStyle = rgbaToCss(c, 1);
      for (const k of ins.keypoints) {
        if ((k[2] ?? 1) < 0.1) continue;
        ctx.beginPath();
        ctx.arc(tx(k[0]), ty(k[1]), 3, 0, Math.PI * 2);
        ctx.fill();
      }
    }
  }, [kp, extents]);

  if (!kp) {
    return <Empty>No keypoints data</Empty>;
  }

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#0a0d12",
        display: "flex",
        flexDirection: "column",
      }}
    >
      <div
        style={{
          padding: "5px 10px",
          fontSize: 11,
          color: "rgba(170,180,200,0.7)",
          borderBottom: "1px solid rgba(255,255,255,0.05)",
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>Keypoints · {kp.schema || kp.schema_name || "custom"}</span>
        <span>{kp.instances.length} instance{kp.instances.length === 1 ? "" : "s"}</span>
      </div>
      <div style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", overflow: "hidden" }}>
        <canvas
          ref={canvasRef}
          style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain" }}
        />
      </div>
    </div>
  );
};

const Empty: React.FC<React.PropsWithChildren> = ({ children }) => (
  <div
    style={{
      width: "100%",
      height: "100%",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      color: "rgba(170,180,200,0.55)",
      fontSize: 12,
      fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
      background: "#0a0d12",
    }}
  >
    {children}
  </div>
);

export default KeypointsVisualizer;
