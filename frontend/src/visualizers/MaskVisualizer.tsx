/**
 * MaskVisualizer — render a 2-D segmentation mask on its own.
 *
 * If an image is part of the composition (passed as an overlay or as the
 * primary value alongside the mask), defer to ``ImageVisualizer`` which
 * handles the alpha-blended composite. Standalone, this component renders the
 * mask alone on a dark background using the encoded image data.
 */

import React from "react";
import { ImageVisualizer } from "./ImageVisualizer";
import { isImageString, isMask, type MaskPayload } from "./_lib/types";

export interface MaskVisualizerProps {
  value: unknown;
  overlays?: unknown[];
  label?: string;
}

export const MaskVisualizer: React.FC<MaskVisualizerProps> = ({ value, overlays }) => {
  // If overlays include an image, defer.
  const imgFromOverlays = (overlays || []).find(isImageString);
  if (imgFromOverlays) {
    return <ImageVisualizer value={imgFromOverlays} overlays={[value, ...(overlays || []).filter((o) => o !== imgFromOverlays)]} />;
  }

  if (!isMask(value)) {
    return <Empty>No mask data</Empty>;
  }

  const m = value as MaskPayload;
  const enc = (m.encoding || "png").toLowerCase();
  const src = m.data_b64 ? `data:image/${enc === "raw" || enc === "alpha" || enc === "u8" ? "png" : enc};base64,${m.data_b64}` : null;

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#0a0d12",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
    >
      {src ? (
        <img
          src={src}
          alt="mask"
          style={{
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
            imageRendering: "pixelated",
            filter: "drop-shadow(0 0 12px rgba(0,180,255,0.3))",
          }}
          draggable={false}
        />
      ) : (
        <span style={{ color: "rgba(170,180,200,0.55)", fontSize: 12 }}>Empty mask</span>
      )}
      <div
        style={{
          position: "absolute",
          bottom: 6,
          right: 6,
          padding: "3px 6px",
          background: "rgba(10,12,18,0.7)",
          backdropFilter: "blur(8px)",
          border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 4,
          color: "#7c8ba8",
          fontSize: 10,
          fontFamily: "'JetBrains Mono','Fira Code',monospace",
        }}
      >
        Mask · {m.width}×{m.height}
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

export default MaskVisualizer;
