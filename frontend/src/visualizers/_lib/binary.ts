/**
 * Binary helpers for visualizer payloads.
 *
 * STRIDE wire payloads carry float arrays as base64-encoded little-endian
 * Float32 buffers (e.g. ``positions_b64``, ``fields_b64`` on ``PointCloud``;
 * ``depth_b64`` on ``DepthMap``). The frontend decodes these once on data
 * arrival and caches the resulting typed array.
 */

/** Decode a base64 string to a ``Float32Array`` (little-endian). */
export function b64ToF32(b64: string): Float32Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return new Float32Array(u8.buffer);
}

/** Decode a base64 string to a ``Uint8Array``. */
export function b64ToU8(b64: string): Uint8Array {
  const bin = atob(b64);
  const u8 = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
  return u8;
}

/** Compute [min, max] of a float array. Returns [0, 1] for empty arrays. */
export function arrayRange(a: Float32Array | number[]): [number, number] {
  if (!a || a.length === 0) return [0, 1];
  let lo = Infinity;
  let hi = -Infinity;
  for (let i = 0; i < a.length; i++) {
    const v = a[i];
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return [0, 1];
  if (hi === lo) hi = lo + 1;
  return [lo, hi];
}
