/**
 * Detections2DVisualizer — table view of 2-D detections.
 *
 * When a Detections2D payload arrives WITHOUT a base image (or alongside one
 * via composition), this component renders the boxes as a clean tabular list:
 * track-id (if any), class, confidence, x/y/w/h.
 *
 * When the payload carries an embedded ``image`` (or one is provided as the
 * primary value) the dashboard composes via ``ImageVisualizer`` instead — the
 * registry routes there. This component is the no-image fallback.
 */

import React from "react";
import { ImageVisualizer } from "./ImageVisualizer";
import { colorFromId, rgbaToCss } from "./_lib/colormaps";
import { isDetections2D, isImageString, type Detections2DPayload } from "./_lib/types";

export interface Detections2DVisualizerProps {
  value: unknown;
  overlays?: unknown[];
  label?: string;
}

export const Detections2DVisualizer: React.FC<Detections2DVisualizerProps> = ({ value, overlays }) => {
  // If the payload carries an image, defer to ImageVisualizer overlay path.
  if (isDetections2D(value) && (value as Detections2DPayload).image) {
    return <ImageVisualizer value={(value as Detections2DPayload).image} overlays={[value, ...(overlays || [])]} />;
  }
  // If overlays include an image, also defer.
  const imgFromOverlays = (overlays || []).find(isImageString);
  if (imgFromOverlays) {
    return <ImageVisualizer value={imgFromOverlays} overlays={[value, ...(overlays || []).filter((o) => o !== imgFromOverlays)]} />;
  }

  if (!isDetections2D(value)) {
    return <Empty>No detections</Empty>;
  }

  const det = value as Detections2DPayload;
  const boxes = det.boxes || [];

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        background: "var(--bg-tertiary, #11141a)",
        borderRadius: 4,
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
      }}
    >
      <div
        style={{
          padding: "6px 10px",
          borderBottom: "1px solid rgba(255,255,255,0.06)",
          fontSize: 11,
          color: "rgba(170,180,200,0.7)",
          fontWeight: 600,
          letterSpacing: 0.5,
          display: "flex",
          justifyContent: "space-between",
        }}
      >
        <span>Detections2D</span>
        <span>
          {boxes.length} box{boxes.length === 1 ? "" : "es"} · {det.image_width}×{det.image_height}
        </span>
      </div>
      <div style={{ flex: 1, overflow: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
          <thead>
            <tr style={{ position: "sticky", top: 0, background: "rgba(20,24,32,0.95)" }}>
              {["", "id", "class", "conf", "x", "y", "w", "h"].map((h, i) => (
                <th
                  key={i}
                  style={{
                    textAlign: i < 4 ? "left" : "right",
                    padding: "4px 8px",
                    color: "rgba(150,160,180,0.7)",
                    fontWeight: 600,
                    borderBottom: "1px solid rgba(255,255,255,0.05)",
                    fontFamily: i >= 4 ? "'JetBrains Mono','Fira Code',monospace" : undefined,
                  }}
                >{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {boxes.map((b, i) => {
              const idForColor = b.track_id ?? b.class_id;
              const c = colorFromId(idForColor);
              return (
                <tr key={i} style={{ background: i % 2 ? "rgba(255,255,255,0.02)" : "transparent" }}>
                  <td style={{ padding: "3px 8px", width: 8 }}>
                    <div style={{ width: 10, height: 10, borderRadius: 2, background: rgbaToCss(c, 1) }} />
                  </td>
                  <td style={{ padding: "3px 8px", color: "#cfd8e8", fontFamily: "'JetBrains Mono','Fira Code',monospace" }}>
                    {b.track_id !== undefined && b.track_id !== null ? `#${b.track_id}` : "—"}
                  </td>
                  <td style={{ padding: "3px 8px", color: "#cfd8e8" }}>{b.class_name}</td>
                  <td style={{ padding: "3px 8px", color: "#7c8ba8", fontFamily: "'JetBrains Mono','Fira Code',monospace" }}>
                    {b.confidence != null ? `${(b.confidence * 100).toFixed(1)}%` : "—"}
                  </td>
                  <td style={numCell}>{b.x1.toFixed(1)}</td>
                  <td style={numCell}>{b.y1.toFixed(1)}</td>
                  <td style={numCell}>{(b.x2 - b.x1).toFixed(1)}</td>
                  <td style={numCell}>{(b.y2 - b.y1).toFixed(1)}</td>
                </tr>
              );
            })}
            {boxes.length === 0 && (
              <tr>
                <td colSpan={8} style={{ padding: 24, textAlign: "center", color: "rgba(170,180,200,0.5)" }}>
                  No boxes
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const numCell: React.CSSProperties = {
  padding: "3px 8px",
  textAlign: "right",
  color: "#7c8ba8",
  fontFamily: "'JetBrains Mono','Fira Code',monospace",
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

export default Detections2DVisualizer;
