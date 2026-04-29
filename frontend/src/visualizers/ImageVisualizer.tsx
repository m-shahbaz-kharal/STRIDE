/**
 * ImageVisualizer — base image preview with optional overlays.
 *
 * Renders an image (data URL, http URL, or wire-form ``Image`` record) and
 * supports interactive pan + zoom. Optional overlays are rendered over the
 * image:
 *   - ``detections2d`` — colored bounding boxes with label + confidence
 *   - ``keypoints``    — skeleton lines + keypoint dots (uses
 *                        ``payload.skeleton`` if present, else COCO-17)
 *   - ``mask``         — alpha-blended segmentation mask
 *
 * The component is purposely dependency-free for pan/zoom (a small wheel +
 * drag handler — three.js / r3f is overkill for 2-D image viewing).
 */

import React, { useCallback, useEffect, useRef, useState } from "react";
import { b64ToU8 } from "./_lib/binary";
import { colorFromId, rgbaToCss } from "./_lib/colormaps";
import {
  COCO17_SKELETON,
  isDetections2D,
  isKeypoints,
  isMask,
  type BBox2DPayload,
  type Detections2DPayload,
  type KeypointsPayload,
  type MaskPayload,
} from "./_lib/types";

export interface ImageVisualizerProps {
  /** Base image: data URL string, http URL, or { _type: "Image", data_b64, format }. */
  value: unknown;
  /** Optional overlays — detections, keypoints, masks. */
  overlays?: unknown[];
  label?: string;
}

interface ResolvedImage {
  src: string;
  width?: number;
  height?: number;
}

function resolveImage(value: unknown): ResolvedImage | null {
  if (typeof value === "string") {
    if (value.startsWith("data:image") || value.startsWith("http")) {
      return { src: value };
    }
    if (value.length > 100 && /^[A-Za-z0-9+/=]+$/.test(value.slice(0, 100))) {
      // Bare base64 — assume JPEG.
      return { src: `data:image/jpeg;base64,${value}` };
    }
    return null;
  }
  if (value && typeof value === "object") {
    const v = value as { _type?: string; data_b64?: string; format?: string; width?: number; height?: number; image?: string };
    if (v._type === "Image" && v.data_b64) {
      const fmt = v.format || "png";
      return { src: `data:image/${fmt};base64,${v.data_b64}`, width: v.width, height: v.height };
    }
    // Detections2D-with-image case
    if (v._type === "Detections2D" && v.image) {
      return { src: typeof v.image === "string" && v.image.startsWith("data:") ? v.image : `data:image/jpeg;base64,${v.image}` };
    }
  }
  return null;
}

interface DecodedOverlays {
  detections: Detections2DPayload[];
  keypoints: KeypointsPayload[];
  masks: MaskPayload[];
}

function gatherOverlays(value: unknown, overlays: unknown[] | undefined): DecodedOverlays {
  const out: DecodedOverlays = { detections: [], keypoints: [], masks: [] };
  const consume = (v: unknown) => {
    if (!v) return;
    if (Array.isArray(v)) { for (const x of v) consume(x); return; }
    if (isDetections2D(v)) out.detections.push(v);
    else if (isKeypoints(v)) out.keypoints.push(v);
    else if (isMask(v)) out.masks.push(v);
  };
  // Note: the primary value can itself be a Detections2D-with-image; in that
  // case we both render the image AND draw the boxes from the same payload.
  consume(value);
  if (overlays) for (const o of overlays) consume(o);
  return out;
}

// ---------------------------------------------------------------------------
// Mask decoder — accepts PNG-encoded base64 OR a raw uint8 alpha buffer.
// ---------------------------------------------------------------------------

async function maskToImageBitmap(mask: MaskPayload): Promise<HTMLImageElement | null> {
  if (!mask.data_b64) return null;
  const enc = (mask.encoding || "png").toLowerCase();
  if (enc === "png" || enc === "jpeg" || enc === "jpg") {
    const img = new Image();
    img.src = `data:image/${enc};base64,${mask.data_b64}`;
    await new Promise<void>((res) => { img.onload = () => res(); img.onerror = () => res(); });
    return img;
  }
  // Raw alpha case — decode base64 to Uint8 then write to a temp canvas.
  if (enc === "raw" || enc === "alpha" || enc === "u8") {
    const u8 = b64ToU8(mask.data_b64);
    const cv = document.createElement("canvas");
    cv.width = mask.width;
    cv.height = mask.height;
    const ctx = cv.getContext("2d");
    if (!ctx) return null;
    const id = ctx.createImageData(mask.width, mask.height);
    for (let i = 0; i < u8.length; i++) {
      id.data[i * 4 + 0] = 80;
      id.data[i * 4 + 1] = 200;
      id.data[i * 4 + 2] = 255;
      id.data[i * 4 + 3] = u8[i];
    }
    ctx.putImageData(id, 0, 0);
    const img = new Image();
    img.src = cv.toDataURL();
    await new Promise<void>((res) => { img.onload = () => res(); img.onerror = () => res(); });
    return img;
  }
  return null;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export const ImageVisualizer: React.FC<ImageVisualizerProps> = ({ value, overlays }) => {
  const containerRef = useRef<HTMLDivElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const overlayRef = useRef<HTMLCanvasElement>(null);
  const [imgInfo, setImgInfo] = useState<{ w: number; h: number } | null>(null);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [maskImages, setMaskImages] = useState<HTMLImageElement[]>([]);

  const resolved = resolveImage(value);
  const decoded = gatherOverlays(value, overlays);

  // If the primary value is a Detections2D and provides .image, surface its boxes too.
  if (value && typeof value === "object" && (value as { _type?: string })._type === "Detections2D") {
    if (!decoded.detections.includes(value as Detections2DPayload)) {
      decoded.detections.push(value as Detections2DPayload);
    }
  }

  // Async decode of mask payloads.
  useEffect(() => {
    let alive = true;
    (async () => {
      const imgs: HTMLImageElement[] = [];
      for (const m of decoded.masks) {
        const img = await maskToImageBitmap(m);
        if (img) imgs.push(img);
      }
      if (alive) setMaskImages(imgs);
    })();
    return () => { alive = false; };
  }, [decoded.masks.length, decoded.masks.map((m) => m.data_b64?.slice(0, 16) || "").join(",")]);

  // Pan + zoom interaction.
  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    e.stopPropagation();
    const factor = e.deltaY > 0 ? 0.9 : 1.1;
    setZoom((z) => Math.max(0.1, Math.min(10, z * factor)));
  }, []);

  const dragRef = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  const onPointerDown = useCallback((e: React.PointerEvent) => {
    if (e.button !== 0 && e.button !== 1) return;
    (e.target as HTMLElement).setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, px: pan.x, py: pan.y };
    e.preventDefault();
    e.stopPropagation();
  }, [pan.x, pan.y]);

  const onPointerMove = useCallback((e: React.PointerEvent) => {
    if (!dragRef.current) return;
    const dx = e.clientX - dragRef.current.x;
    const dy = e.clientY - dragRef.current.y;
    setPan({ x: dragRef.current.px + dx, y: dragRef.current.py + dy });
  }, []);

  const onPointerUp = useCallback((e: React.PointerEvent) => {
    dragRef.current = null;
    try { (e.target as HTMLElement).releasePointerCapture(e.pointerId); } catch { /* ignore */ }
  }, []);

  const reset = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  // Draw overlays onto the canvas matched to the rendered image size.
  useEffect(() => {
    const cv = overlayRef.current;
    if (!cv || !imgInfo) return;
    cv.width = imgInfo.w;
    cv.height = imgInfo.h;
    const ctx = cv.getContext("2d");
    if (!ctx) return;
    ctx.clearRect(0, 0, cv.width, cv.height);

    // Masks first (under boxes / keypoints).
    for (const img of maskImages) {
      ctx.globalAlpha = 0.5;
      ctx.drawImage(img, 0, 0, cv.width, cv.height);
      ctx.globalAlpha = 1;
    }

    // Detections.
    for (const det of decoded.detections) {
      // Detection coords are in source-image space. Scale to canvas if width/height differ.
      const sx = cv.width / (det.image_width || cv.width);
      const sy = cv.height / (det.image_height || cv.height);
      for (const b of det.boxes as BBox2DPayload[]) {
        const idForColor = b.track_id ?? b.class_id;
        const color = colorFromId(idForColor);
        const stroke = rgbaToCss(color, 1);
        const x = b.x1 * sx, y = b.y1 * sy;
        const w = (b.x2 - b.x1) * sx;
        const h = (b.y2 - b.y1) * sy;
        ctx.lineWidth = Math.max(1.5, Math.min(cv.width, cv.height) * 0.003);
        ctx.strokeStyle = stroke;
        ctx.strokeRect(x, y, w, h);

        const label = `${b.track_id !== undefined && b.track_id !== null ? `#${b.track_id} ` : ""}${b.class_name}${b.confidence ? ` ${Math.round(b.confidence * 100)}%` : ""}`;
        ctx.font = `bold ${Math.max(11, cv.width * 0.012)}px 'Inter','Segoe UI',system-ui,sans-serif`;
        const m = ctx.measureText(label);
        const padX = 4, padY = 2;
        const tw = m.width + padX * 2;
        const th = (m.actualBoundingBoxAscent || 12) + padY * 2;
        const ty = Math.max(0, y - th);
        ctx.fillStyle = rgbaToCss(color, 0.85);
        ctx.fillRect(x, ty, tw, th);
        ctx.fillStyle = "#0c0e14";
        ctx.fillText(label, x + padX, ty + (m.actualBoundingBoxAscent || 12) + padY);
      }
    }

    // Keypoints.
    for (const kp of decoded.keypoints) {
      const skel = (kp.skeleton && kp.skeleton.length ? kp.skeleton : COCO17_SKELETON);
      for (let inst = 0; inst < kp.instances.length; inst++) {
        const ins = kp.instances[inst];
        const color = colorFromId(inst);
        const cssC = rgbaToCss(color, 0.95);
        // Skeleton lines.
        ctx.strokeStyle = cssC;
        ctx.lineWidth = Math.max(1.5, cv.width * 0.0025);
        for (const [a, b] of skel) {
          const ka = ins.keypoints[a];
          const kb = ins.keypoints[b];
          if (!ka || !kb) continue;
          if ((ka[2] ?? 1) < 0.1 || (kb[2] ?? 1) < 0.1) continue;
          ctx.beginPath();
          ctx.moveTo(ka[0], ka[1]);
          ctx.lineTo(kb[0], kb[1]);
          ctx.stroke();
        }
        // Keypoint dots.
        ctx.fillStyle = cssC;
        const dotR = Math.max(2.5, cv.width * 0.003);
        for (const k of ins.keypoints) {
          if ((k[2] ?? 1) < 0.1) continue;
          ctx.beginPath();
          ctx.arc(k[0], k[1], dotR, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }
  }, [imgInfo, decoded.detections, decoded.keypoints, maskImages]);

  // Track loaded image natural dims for canvas alignment.
  const onImgLoad = useCallback((e: React.SyntheticEvent<HTMLImageElement>) => {
    const el = e.currentTarget;
    setImgInfo({ w: el.naturalWidth, h: el.naturalHeight });
    imgRef.current = el;
  }, []);

  if (!resolved) {
    return (
      <Empty>
        {value === undefined || value === null
          ? "No image data"
          : "Unsupported image payload"}
      </Empty>
    );
  }

  return (
    <div
      ref={containerRef}
      onWheel={onWheel}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onDoubleClick={reset}
      style={{
        width: "100%",
        height: "100%",
        position: "relative",
        background: "#0a0d12",
        overflow: "hidden",
        cursor: dragRef.current ? "grabbing" : "grab",
        touchAction: "none",
      }}
    >
      <div
        style={{
          position: "absolute",
          top: "50%",
          left: "50%",
          transform: `translate(-50%, -50%) translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
          transformOrigin: "center center",
        }}
      >
        <img
          src={resolved.src}
          alt="image"
          onLoad={onImgLoad}
          style={{
            display: "block",
            maxWidth: "100%",
            maxHeight: "100%",
            objectFit: "contain",
            pointerEvents: "none",
          }}
          draggable={false}
        />
        {imgInfo && (
          <canvas
            ref={overlayRef}
            style={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              pointerEvents: "none",
            }}
          />
        )}
      </div>

      <div
        style={{
          position: "absolute",
          bottom: 6,
          right: 6,
          display: "flex",
          gap: 4,
          padding: "3px 6px",
          background: "rgba(10, 12, 18, 0.7)",
          backdropFilter: "blur(8px)",
          border: "1px solid rgba(255,255,255,0.06)",
          borderRadius: 4,
          color: "#7c8ba8",
          fontSize: 10,
          fontFamily: "'JetBrains Mono','Fira Code',monospace",
          pointerEvents: "none",
        }}
      >
        <span>{Math.round(zoom * 100)}%</span>
        {imgInfo && <span>· {imgInfo.w}×{imgInfo.h}</span>}
        {decoded.detections.reduce((s, d) => s + d.boxes.length, 0) > 0 && (
          <span>· {decoded.detections.reduce((s, d) => s + d.boxes.length, 0)} det</span>
        )}
        {decoded.keypoints.reduce((s, k) => s + k.instances.length, 0) > 0 && (
          <span>· {decoded.keypoints.reduce((s, k) => s + k.instances.length, 0)} kp</span>
        )}
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

export default ImageVisualizer;
