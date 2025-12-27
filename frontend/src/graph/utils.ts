import { NodeExecutionStatus, TypeDescriptor } from "../types";

export const PORT_TYPE_COLORS: Record<string, string> = {
  int: "#4a9eff",
  float: "#60a5fa",
  number: "#60a5fa",
  image: "#e85aad",
  stream: "#0fb5a9",
  url: "#7c3aed",
  boolean: "#f59e0b",
  string: "#10b981",
  any: "#94a3b8",
  unknown: "#cbd5e1",
  list: "#7dd3fc",
  map: "#facc15",
  record: "#a855f7",
  tensor: "#22d3ee",
  control: "#f97316",
};

export const PORT_ROW_HEIGHT = 42;
export const PARAM_ROW_HEIGHT = 26;
export const HEADER_HEIGHT = 70;
export const MIN_NODE_WIDTH = 260;

export const getExecutionStatusClass = (status?: NodeExecutionStatus): string => {
  switch (status) {
    case "running":
      return "node-running";
    case "queued":
      return "node-queued";
    case "completed":
      return "node-executed";
    case "error":
      return "node-error";
    default:
      return "";
  }
};

const typeToColorKey = (type?: TypeDescriptor | string): string => {
  if (!type) return "any";
  if (typeof type === "string") return type.toLowerCase();
  if (type.kind === "list" || type.kind === "map" || type.kind === "record" || type.kind === "tensor") {
    return type.kind;
  }
  return type.kind || "any";
};

export const getPortTypeColor = (type?: TypeDescriptor | string): string => {
  const key = typeToColorKey(type);
  return PORT_TYPE_COLORS[key] || PORT_TYPE_COLORS.any;
};

export const formatPortTypeLabel = (type?: TypeDescriptor | string): string => {
  if (!type) return "Any";
  if (typeof type === "string") {
    const normalized = type.toLowerCase();
    if (normalized === "any") return "Any";
    const label = normalized.replace(/_/g, " ");
    return label.charAt(0).toUpperCase() + label.slice(1);
  }
  const { kind } = type;
  if (kind === "list" && type.item) return `List<${formatPortTypeLabel(type.item)}>`;
  if (kind === "map" && type.value) return `Map<${formatPortTypeLabel(type.value)}>`;
  if (kind === "tensor") {
    const dtype = type.metadata?.dtype ?? "tensor";
    return `Tensor<${dtype}>`;
  }
  return kind.charAt(0).toUpperCase() + kind.slice(1);
};

export const computeNodeDimensions = (
  maxPorts: number,
  options?: { paramCount?: number; minWidth?: number }
) => {
  const paramCount = options?.paramCount ?? 0;
  const minWidth = options?.minWidth ?? MIN_NODE_WIDTH;
  const height = HEADER_HEIGHT + maxPorts * PORT_ROW_HEIGHT + paramCount * PARAM_ROW_HEIGHT + 8;
  return {
    width: minWidth,
    height,
  };
};

// Check if a line segment intersects a rectangle
export const lineIntersectsRect = (
  x1: number, y1: number, x2: number, y2: number,
  rx: number, ry: number, rw: number, rh: number
): boolean => {
  const pointInRect = (px: number, py: number) =>
    px >= rx && px <= rx + rw && py >= ry && py <= ry + rh;

  if (pointInRect(x1, y1) || pointInRect(x2, y2)) return true;

  const lineIntersectsLine = (
    ax1: number, ay1: number, ax2: number, ay2: number,
    bx1: number, by1: number, bx2: number, by2: number
  ): boolean => {
    const denom = (by2 - by1) * (ax2 - ax1) - (bx2 - bx1) * (ay2 - ay1);
    if (Math.abs(denom) < 0.0001) return false;

    const ua = ((bx2 - bx1) * (ay1 - by1) - (by2 - by1) * (ax1 - bx1)) / denom;
    const ub = ((ax2 - ax1) * (ay1 - by1) - (ay2 - ay1) * (ax1 - bx1)) / denom;

    return ua >= 0 && ua <= 1 && ub >= 0 && ub <= 1;
  };

  return (
    lineIntersectsLine(x1, y1, x2, y2, rx, ry, rx + rw, ry) ||
    lineIntersectsLine(x1, y1, x2, y2, rx, ry + rh, rx + rw, ry + rh) ||
    lineIntersectsLine(x1, y1, x2, y2, rx, ry, rx, ry + rh) ||
    lineIntersectsLine(x1, y1, x2, y2, rx + rw, ry, rx + rw, ry + rh)
  );
};

// Sample points along a bezier curve and check if any segment intersects the rect
export const bezierIntersectsRect = (
  sourceX: number, sourceY: number,
  targetX: number, targetY: number,
  rx: number, ry: number, rw: number, rh: number
): boolean => {
  const centerX = (sourceX + targetX) / 2;
  const cp1x = centerX;
  const cp1y = sourceY;
  const cp2x = centerX;
  const cp2y = targetY;

  const samples = 20;
  let prevX = sourceX;
  let prevY = sourceY;

  for (let i = 1; i <= samples; i++) {
    const t = i / samples;
    const t2 = t * t;
    const t3 = t2 * t;
    const mt = 1 - t;
    const mt2 = mt * mt;
    const mt3 = mt2 * mt;

    const x = mt3 * sourceX + 3 * mt2 * t * cp1x + 3 * mt * t2 * cp2x + t3 * targetX;
    const y = mt3 * sourceY + 3 * mt2 * t * cp1y + 3 * mt * t2 * cp2y + t3 * targetY;

    if (lineIntersectsRect(prevX, prevY, x, y, rx, ry, rw, rh)) {
      return true;
    }

    prevX = x;
    prevY = y;
  }

  return false;
};
