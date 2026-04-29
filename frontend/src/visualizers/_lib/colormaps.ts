/**
 * Colormaps used by the 3D viewer, depth map, and other heatmap-style
 * visualizers.
 *
 * All colormaps return ``[r, g, b]`` triples in [0, 1]. The polynomial
 * approximations are GLSL-port friendly (see Scene3DVisualizer's shader).
 */

export type ColormapName = "viridis" | "turbo" | "grayscale" | "plasma" | "magma";

/** Turbo colormap (Mikola Mikola/Anton Mikhailov, 2019). t in [0,1]. */
export function turbo(t: number): [number, number, number] {
  const x = clamp01(t);
  const r = clamp01(0.13572 + x * (4.6153 + x * (-42.66 + x * (132.13 + x * (-152.95 + x * 56.67)))));
  const g = clamp01(0.09140 + x * (2.1643 + x * (4.8428 + x * (-27.66 + x * (29.04 + x * -8.36)))));
  const b = clamp01(0.10667 + x * (12.486 + x * (-60.46 + x * (109.98 + x * (-89.09 + x * 25.79)))));
  return [r, g, b];
}

/** Viridis colormap (matplotlib-derived polynomial). t in [0,1]. */
export function viridis(t: number): [number, number, number] {
  const x = clamp01(t);
  const r = clamp01(0.2777273 + x * (-0.1058086 + x * (-2.9510 + x * (10.0 + x * (-13.6 + x * 6.34)))));
  const g = clamp01(-0.00204 + x * (1.8 + x * (-1.55 + x * (0.8 + x * (-0.4 + x * 0.05)))));
  const b = clamp01(0.329 + x * (1.84 + x * (-7.66 + x * (12.83 + x * (-9.11 + x * 2.36)))));
  return [r, g, b];
}

/** Grayscale colormap. t in [0,1]. */
export function grayscale(t: number): [number, number, number] {
  const v = clamp01(t);
  return [v, v, v];
}

/** Plasma colormap polynomial fit. */
export function plasma(t: number): [number, number, number] {
  const x = clamp01(t);
  const r = clamp01(0.05873 + x * (2.176 + x * (-2.689 + x * (1.43 + x * 0.005))));
  const g = clamp01(0.0233 + x * (0.247 + x * (1.108 + x * (-1.55 + x * 0.144))));
  const b = clamp01(0.5331 + x * (1.43 + x * (-3.73 + x * (3.81 + x * -1.49))));
  return [r, g, b];
}

/** Magma colormap polynomial fit. */
export function magma(t: number): [number, number, number] {
  const x = clamp01(t);
  const r = clamp01(0.00306 + x * (-0.0016 + x * (1.2 + x * (-0.16 + x * -0.05))));
  const g = clamp01(-0.00176 + x * (-0.225 + x * (1.92 + x * (-1.71 + x * 0.99))));
  const b = clamp01(-0.014 + x * (1.5 + x * (-3.1 + x * (3.36 + x * -1.5))));
  return [r, g, b];
}

export const COLORMAPS: Record<ColormapName, (t: number) => [number, number, number]> = {
  viridis,
  turbo,
  grayscale,
  plasma,
  magma,
};

/** Apply a colormap by name. */
export function applyColormap(name: ColormapName, t: number): [number, number, number] {
  return COLORMAPS[name](t);
}

function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

/**
 * Stable color from an integer id (e.g. track / class id). Uses the golden
 * ratio for a well-distributed hue palette.
 */
export function colorFromId(id: number): [number, number, number] {
  const golden = 0.61803398875;
  const h = ((id * golden) % 1 + 1) % 1;
  const s = 0.7;
  const v = 0.95;
  return hsvToRgb(h, s, v);
}

function hsvToRgb(h: number, s: number, v: number): [number, number, number] {
  const i = Math.floor(h * 6);
  const f = h * 6 - i;
  const p = v * (1 - s);
  const q = v * (1 - f * s);
  const t = v * (1 - (1 - f) * s);
  switch (i % 6) {
    case 0: return [v, t, p];
    case 1: return [q, v, p];
    case 2: return [p, v, t];
    case 3: return [p, q, v];
    case 4: return [t, p, v];
    default: return [v, p, q];
  }
}

/** Pack [r,g,b] (0-1) into a CSS ``rgb()`` string. */
export function rgbToCss([r, g, b]: [number, number, number]): string {
  return `rgb(${(r * 255) | 0}, ${(g * 255) | 0}, ${(b * 255) | 0})`;
}

/** Pack [r,g,b] (0-1) into a CSS ``rgba()`` string. */
export function rgbaToCss([r, g, b]: [number, number, number], a: number): string {
  return `rgba(${(r * 255) | 0}, ${(g * 255) | 0}, ${(b * 255) | 0}, ${a})`;
}
