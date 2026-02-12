import React, { useRef, useEffect, useCallback, useState, memo } from "react";

// ═══════════════════════════════════════════════════════════════════════════
// DATA TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface PointCloudData {
    _type: "PointCloud";
    num_points: number;
    positions_b64?: string;
    fields_b64?: Record<string, string>;
    positions?: number[][];
    fields?: Record<string, number[]>;
}

interface BBox3D {
    id: number;
    center: number[];
    size: number[];
}

interface Region3D {
    name: string;
    center: number[];
    size: number[];
}

interface Scene3DData {
    _type: "Scene3D";
    point_cloud: PointCloudData;
    boxes: BBox3D[];
    regions: Region3D[];
    occupancy: number[];
}

interface Props {
    data: Scene3DData;
}

type ColorMode = "height" | "signal" | "reflectivity" | "near_ir" | "solid";
type NavMode = "rotate" | "pan" | "zoom";

// ═══════════════════════════════════════════════════════════════════════════
// UTILITY
// ═══════════════════════════════════════════════════════════════════════════

function b64ToF32(b64: string): Float32Array {
    const bin = atob(b64);
    const u8 = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) u8[i] = bin.charCodeAt(i);
    return new Float32Array(u8.buffer);
}

// Color palette for object IDs (distinct colors)
const ID_COLORS: [number, number, number][] = [
    [0.0, 0.8, 0.4],   // Green
    [0.2, 0.6, 1.0],   // Blue
    [1.0, 0.6, 0.0],   // Orange
    [0.8, 0.2, 0.8],   // Purple
    [1.0, 0.8, 0.0],   // Yellow
    [0.0, 0.8, 0.8],   // Cyan
    [1.0, 0.3, 0.3],   // Red
    [0.6, 0.4, 0.2],   // Brown
];

function getColorForId(id: number): [number, number, number] {
    return ID_COLORS[(id - 1) % ID_COLORS.length];
}

// ═══════════════════════════════════════════════════════════════════════════
// UI COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

const panelStyle: React.CSSProperties = {
    background: "rgba(10, 12, 18, 0.65)",
    backdropFilter: "blur(12px) saturate(1.4)",
    WebkitBackdropFilter: "blur(12px) saturate(1.4)",
    border: "1px solid rgba(255,255,255,0.07)",
    borderRadius: 6,
    padding: 3,
    display: "flex",
    gap: 2,
    pointerEvents: "auto",
};

const btnBase: React.CSSProperties = {
    border: "1px solid transparent",
    borderRadius: 4,
    fontSize: 11,
    fontWeight: 600,
    fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
    cursor: "pointer",
    transition: "all 0.12s ease",
    outline: "none",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    minWidth: 26,
    height: 26,
    padding: "0 7px",
    letterSpacing: 0.3,
};

interface TBProps {
    label: string;
    tooltip: string;
    active?: boolean;
    onClick: () => void;
    compact?: boolean;
}

const TB = memo(({ label, tooltip, active, onClick, compact }: TBProps) => (
    <button
        title={tooltip}
        style={{
            ...btnBase,
            minWidth: compact ? 26 : undefined,
            padding: compact ? "0 5px" : "0 7px",
            background: active
                ? "linear-gradient(135deg, rgba(56,128,255,0.35), rgba(80,180,255,0.25))"
                : "rgba(255,255,255,0.04)",
            border: active
                ? "1px solid rgba(80,160,255,0.5)"
                : "1px solid rgba(255,255,255,0.06)",
            color: active ? "#8ac4ff" : "rgba(200,200,210,0.7)",
            boxShadow: active ? "0 0 8px rgba(56,128,255,0.3), inset 0 0 6px rgba(56,128,255,0.1)" : "none",
        }}
        onMouseDown={(e) => { e.stopPropagation(); e.preventDefault(); }}
        onPointerDown={(e) => { e.stopPropagation(); e.preventDefault(); }}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); onClick(); }}
    >{label}</button>
));

// ═══════════════════════════════════════════════════════════════════════════
// SHADERS
// ═══════════════════════════════════════════════════════════════════════════

const POINT_VS = `
attribute vec3 a_pos;
attribute float a_h;
attribute float a_f1;
attribute float a_f2;
attribute float a_f3;

uniform mat4 u_mvp;
uniform float u_ps;
uniform int u_cm;
uniform vec2 u_range;

varying float v_t;
varying float v_solid;

void main() {
    gl_Position = u_mvp * vec4(a_pos, 1.0);
    gl_PointSize = u_ps;
    float val = a_h;
    if (u_cm == 1) val = a_f1;
    else if (u_cm == 2) val = a_f2;
    else if (u_cm == 3) val = a_f3;
    v_t = clamp((val - u_range.x) / max(u_range.y - u_range.x, 0.0001), 0.0, 1.0);
    v_solid = u_cm == 4 ? 1.0 : 0.0;
}
`;

const POINT_FS = `
precision mediump float;
varying float v_t;
varying float v_solid;

vec3 turbo(float t) {
    float r = 0.13572+t*(4.6153+t*(-42.66+t*(132.13+t*(-152.95+t*56.67))));
    float g = 0.09140+t*(2.1643+t*(4.8428+t*(-27.66+t*(29.04+t*(-8.36)))));
    float b = 0.10667+t*(12.486+t*(-60.46+t*(109.98+t*(-89.09+t*25.79))));
    return clamp(vec3(r,g,b), 0.0, 1.0);
}

void main() {
    vec2 c = gl_PointCoord - 0.5;
    if (dot(c,c) > 0.25) discard;
    vec3 col = v_solid > 0.5 ? vec3(0.25,0.72,1.0) : turbo(v_t);
    gl_FragColor = vec4(col, 1.0);
}
`;

const LINE_VS = `
attribute vec3 a_pos;
attribute vec3 a_col;
uniform mat4 u_mvp;
varying vec3 v_col;
void main() { gl_Position = u_mvp * vec4(a_pos,1.0); v_col = a_col; }
`;

const LINE_FS = `
precision mediump float;
varying vec3 v_col;
void main() { gl_FragColor = vec4(v_col,1.0); }
`;

// Shader for transparent regions
const REGION_VS = `
attribute vec3 a_pos;
uniform mat4 u_mvp;
void main() { gl_Position = u_mvp * vec4(a_pos, 1.0); }
`;

const REGION_FS = `
precision mediump float;
uniform vec4 u_color;
void main() { gl_FragColor = u_color; }
`;

// ═══════════════════════════════════════════════════════════════════════════
// MATH HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function m4Mul(a: Float32Array, b: Float32Array): Float32Array {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
        for (let r = 0; r < 4; r++)
            o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
    return o;
}

function m4Persp(fov: number, asp: number, zn: number, zf: number): Float32Array {
    const f = 1 / Math.tan(fov / 2), m = new Float32Array(16);
    m[0] = f / asp; m[5] = f; m[10] = (zf + zn) / (zn - zf); m[11] = -1; m[14] = 2 * zf * zn / (zn - zf);
    return m;
}

function m4Look(eye: number[], ctr: number[], up: number[]): Float32Array {
    let fx = eye[0] - ctr[0], fy = eye[1] - ctr[1], fz = eye[2] - ctr[2];
    let l = Math.hypot(fx, fy, fz) || 1; fx /= l; fy /= l; fz /= l;
    let rx = up[1] * fz - up[2] * fy, ry = up[2] * fx - up[0] * fz, rz = up[0] * fy - up[1] * fx;
    l = Math.hypot(rx, ry, rz) || 1; rx /= l; ry /= l; rz /= l;
    const ux = fy * rz - fz * ry, uy = fz * rx - fx * rz, uz = fx * ry - fy * rx;
    const m = new Float32Array(16);
    m[0] = rx; m[1] = ux; m[2] = fx;
    m[4] = ry; m[5] = uy; m[6] = fy;
    m[8] = rz; m[9] = uz; m[10] = fz;
    m[12] = -(rx * eye[0] + ry * eye[1] + rz * eye[2]);
    m[13] = -(ux * eye[0] + uy * eye[1] + uz * eye[2]);
    m[14] = -(fx * eye[0] + fy * eye[1] + fz * eye[2]);
    m[15] = 1;
    return m;
}

// ═══════════════════════════════════════════════════════════════════════════
// GL HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function mkShader(gl: WebGLRenderingContext, src: string, type: number) {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src); gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) throw new Error(gl.getShaderInfoLog(s) || "");
    return s;
}

function mkProg(gl: WebGLRenderingContext, vs: string, fs: string) {
    const p = gl.createProgram()!;
    gl.attachShader(p, mkShader(gl, vs, gl.VERTEX_SHADER));
    gl.attachShader(p, mkShader(gl, fs, gl.FRAGMENT_SHADER));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(p) || "");
    return p;
}

function mkBuf(gl: WebGLRenderingContext, data: Float32Array, usage?: number) {
    const b = gl.createBuffer()!;
    gl.bindBuffer(gl.ARRAY_BUFFER, b);
    gl.bufferData(gl.ARRAY_BUFFER, data, usage ?? gl.DYNAMIC_DRAW);
    return b;
}

// ═══════════════════════════════════════════════════════════════════════════
// GEOMETRY BUILDERS
// ═══════════════════════════════════════════════════════════════════════════

function buildWireframeCube(center: number[], size: number[]): Float32Array {
    const [cx, cy, cz] = center;
    const [sx, sy, sz] = size;
    const hx = sx / 2, hy = sy / 2, hz = sz / 2;

    // 8 corners
    const corners = [
        [cx - hx, cy - hy, cz - hz],
        [cx + hx, cy - hy, cz - hz],
        [cx + hx, cy + hy, cz - hz],
        [cx - hx, cy + hy, cz - hz],
        [cx - hx, cy - hy, cz + hz],
        [cx + hx, cy - hy, cz + hz],
        [cx + hx, cy + hy, cz + hz],
        [cx - hx, cy + hy, cz + hz],
    ];

    // 12 edges (pairs of corner indices)
    const edges = [
        [0, 1], [1, 2], [2, 3], [3, 0], // bottom
        [4, 5], [5, 6], [6, 7], [7, 4], // top
        [0, 4], [1, 5], [2, 6], [3, 7], // verticals
    ];

    const verts: number[] = [];
    for (const [a, b] of edges) {
        verts.push(...corners[a], ...corners[b]);
    }

    return new Float32Array(verts);
}

function buildSolidCube(center: number[], size: number[]): Float32Array {
    const [cx, cy, cz] = center;
    const [sx, sy, sz] = size;
    const hx = sx / 2, hy = sy / 2, hz = sz / 2;

    // 8 corners
    const c = [
        [cx - hx, cy - hy, cz - hz],
        [cx + hx, cy - hy, cz - hz],
        [cx + hx, cy + hy, cz - hz],
        [cx - hx, cy + hy, cz - hz],
        [cx - hx, cy - hy, cz + hz],
        [cx + hx, cy - hy, cz + hz],
        [cx + hx, cy + hy, cz + hz],
        [cx - hx, cy + hy, cz + hz],
    ];

    // 6 faces, 2 triangles each (12 triangles, 36 vertices)
    const faces = [
        [0, 1, 2, 0, 2, 3], // bottom
        [4, 6, 5, 4, 7, 6], // top
        [0, 4, 5, 0, 5, 1], // front
        [2, 6, 7, 2, 7, 3], // back
        [0, 3, 7, 0, 7, 4], // left
        [1, 5, 6, 1, 6, 2], // right
    ];

    const verts: number[] = [];
    for (const face of faces) {
        for (const i of face) {
            verts.push(...c[i]);
        }
    }

    return new Float32Array(verts);
}

// ═══════════════════════════════════════════════════════════════════════════
// DATA PARSER
// ═══════════════════════════════════════════════════════════════════════════

interface ParsedCloud {
    pos: Float32Array;
    h: Float32Array;
    fields: Record<string, Float32Array>;
    n: number;
    bounds: { min: [number, number, number]; max: [number, number, number] };
}

function parseCloud(d: PointCloudData | null): ParsedCloud | null {
    if (!d) return null;
    const N = d.num_points;
    if (!N) return null;

    let pos: Float32Array;
    if (d.positions_b64) {
        pos = b64ToF32(d.positions_b64);
    } else if (d.positions) {
        pos = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            const p = d.positions[i];
            pos[i * 3] = p[0]; pos[i * 3 + 1] = p[1]; pos[i * 3 + 2] = p[2];
        }
    } else return null;

    const h = new Float32Array(N);
    for (let i = 0; i < N; i++) h[i] = pos[i * 3 + 2];

    const fields: Record<string, Float32Array> = {};
    if (d.fields_b64) {
        for (const [k, v] of Object.entries(d.fields_b64)) fields[k] = b64ToF32(v);
    } else if (d.fields) {
        for (const [k, a] of Object.entries(d.fields)) fields[k] = new Float32Array(a);
    }

    let x0 = Infinity, y0 = Infinity, z0 = Infinity, x1 = -Infinity, y1 = -Infinity, z1 = -Infinity;
    for (let i = 0; i < N; i++) {
        const x = pos[i * 3], y = pos[i * 3 + 1], z = pos[i * 3 + 2];
        if (x < x0) x0 = x; if (x > x1) x1 = x;
        if (y < y0) y0 = y; if (y > y1) y1 = y;
        if (z < z0) z0 = z; if (z > z1) z1 = z;
    }
    return { pos, h, fields, n: N, bounds: { min: [x0, y0, z0], max: [x1, y1, z1] } };
}

function fieldRange(arr: Float32Array): [number, number] {
    let lo = Infinity, hi = -Infinity;
    for (let i = 0; i < arr.length; i++) { if (arr[i] < lo) lo = arr[i]; if (arr[i] > hi) hi = arr[i]; }
    if (hi === lo) hi = lo + 1;
    return [lo, hi];
}

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const Scene3DWidget: React.FC<Props> = ({ data }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const boxRef = useRef<HTMLDivElement>(null);
    const glRef = useRef<WebGLRenderingContext | null>(null);
    const hoverRef = useRef(false);

    const cam = useRef({ th: Math.PI / 4, ph: Math.PI / 6, d: 50, tx: 0, ty: 0, tz: 0, ps: 2, zUp: 1 as 1 | -1 });

    const [colorMode, setColorMode] = useState<ColorMode>("height");
    const [nav, setNav] = useState<NavMode>("rotate");
    const [info, setInfo] = useState("");
    const [fpsVal, setFps] = useState(0);
    const [showBoxes, setShowBoxes] = useState(true);
    const [showRegions, setShowRegions] = useState(true);

    // Hover state for labels
    const [hoverLabel, setHoverLabel] = useState<{ text: string; x: number; y: number } | null>(null);

    const navRef = useRef<NavMode>(nav);
    navRef.current = nav;
    const cmRef = useRef<ColorMode>(colorMode);
    cmRef.current = colorMode;

    const gpu = useRef<{
        pp: WebGLProgram;
        lp: WebGLProgram;
        rp: WebGLProgram;
        posBuf: WebGLBuffer;
        hBuf: WebGLBuffer;
        fBufs: Record<string, WebGLBuffer>;
        axBuf: WebGLBuffer;
        axCBuf: WebGLBuffer;
        n: number;
        bounds: ParsedCloud["bounds"];
        ranges: Record<string, [number, number]>;
        u: Record<string, WebGLUniformLocation | null>;
        a: Record<string, number>;
    } | null>(null);

    // Dynamic buffers for boxes and regions
    const boxData = useRef<{ verts: Float32Array; colors: Float32Array; count: number } | null>(null);
    const regionData = useRef<{ verts: Float32Array; color: [number, number, number, number]; count: number }[]>([]);

    const fitted = useRef(false);
    const fc = useRef(0);
    const lt = useRef(performance.now());

    // Store box centers for hover detection
    const boxCentersRef = useRef<{ id: number; center: number[]; screenPos?: [number, number] }[]>([]);

    // Camera control
    const fit = useCallback(() => {
        const g = gpu.current; if (!g) return;
        const { min, max } = g.bounds;
        const c = cam.current;
        c.tx = (min[0] + max[0]) / 2; c.ty = (min[1] + max[1]) / 2; c.tz = (min[2] + max[2]) / 2;
        c.d = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1) * 1.5;
        c.th = Math.PI / 4; c.ph = Math.PI / 6;
    }, []);

    const viewTop = useCallback(() => { cam.current.th = 0; cam.current.ph = Math.PI / 2 - 0.01; }, []);
    const viewFront = useCallback(() => { cam.current.th = -Math.PI / 2; cam.current.ph = 0; }, []);
    const viewSide = useCallback(() => { cam.current.th = 0; cam.current.ph = 0; }, []);
    const viewIso = useCallback(() => { cam.current.th = Math.PI / 4; cam.current.ph = Math.PI / 6; }, []);
    const flipV = useCallback(() => { cam.current.zUp *= -1; }, []);

    // Process scene data
    useEffect(() => {
        const cv = canvasRef.current;
        if (!cv || !data || data._type !== "Scene3D") return;

        const cloud = data.point_cloud;
        const p = parseCloud(cloud);
        if (!p) return;

        const gl = glRef.current;
        if (!gl) return;

        let pp: WebGLProgram, lp: WebGLProgram, rp: WebGLProgram;
        if (gpu.current) {
            pp = gpu.current.pp;
            lp = gpu.current.lp;
            rp = gpu.current.rp;
            gl.deleteBuffer(gpu.current.posBuf);
            gl.deleteBuffer(gpu.current.hBuf);
            for (const b of Object.values(gpu.current.fBufs)) gl.deleteBuffer(b);
            gl.deleteBuffer(gpu.current.axBuf);
            gl.deleteBuffer(gpu.current.axCBuf);
        } else {
            pp = mkProg(gl, POINT_VS, POINT_FS);
            lp = mkProg(gl, LINE_VS, LINE_FS);
            rp = mkProg(gl, REGION_VS, REGION_FS);
        }

        const posBuf = mkBuf(gl, p.pos);
        const hBuf = mkBuf(gl, p.h);
        const fBufs: Record<string, WebGLBuffer> = {};
        const ranges: Record<string, [number, number]> = { height: fieldRange(p.h) };
        for (const [k, arr] of Object.entries(p.fields)) {
            fBufs[k] = mkBuf(gl, arr);
            ranges[k] = fieldRange(arr);
        }

        // Axis
        const { min, max } = p.bounds;
        const ext = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2]) || 10;
        const al = ext * 0.08;
        const cx = (min[0] + max[0]) / 2, cy = (min[1] + max[1]) / 2;
        const axBuf = mkBuf(gl, new Float32Array([
            cx, cy, min[2], cx + al, cy, min[2],
            cx, cy, min[2], cx, cy + al, min[2],
            cx, cy, min[2], cx, cy, min[2] + al,
        ]), gl.STATIC_DRAW);
        const axCBuf = mkBuf(gl, new Float32Array([
            1, .2, .2, 1, .2, .2, .2, 1, .2, .2, 1, .2, .3, .5, 1, .3, .5, 1,
        ]), gl.STATIC_DRAW);

        const u: Record<string, WebGLUniformLocation | null> = {
            mvp: gl.getUniformLocation(pp, "u_mvp"),
            ps: gl.getUniformLocation(pp, "u_ps"),
            cm: gl.getUniformLocation(pp, "u_cm"),
            rng: gl.getUniformLocation(pp, "u_range"),
            lmvp: gl.getUniformLocation(lp, "u_mvp"),
            rmvp: gl.getUniformLocation(rp, "u_mvp"),
            rcolor: gl.getUniformLocation(rp, "u_color"),
        };
        const a: Record<string, number> = {
            pos: gl.getAttribLocation(pp, "a_pos"),
            h: gl.getAttribLocation(pp, "a_h"),
            f1: gl.getAttribLocation(pp, "a_f1"),
            f2: gl.getAttribLocation(pp, "a_f2"),
            f3: gl.getAttribLocation(pp, "a_f3"),
            lp: gl.getAttribLocation(lp, "a_pos"),
            lc: gl.getAttribLocation(lp, "a_col"),
            rp: gl.getAttribLocation(rp, "a_pos"),
        };

        gpu.current = { pp, lp, rp, posBuf, hBuf, fBufs, axBuf, axCBuf, n: p.n, bounds: p.bounds, ranges, u, a };

        if (!fitted.current) { fit(); fitted.current = true; }

        // Build box geometry
        const boxes = data.boxes || [];
        if (boxes.length > 0) {
            const allVerts: number[] = [];
            const allColors: number[] = [];
            boxCentersRef.current = [];

            for (const box of boxes) {
                const wireframe = buildWireframeCube(box.center, box.size);
                const color = getColorForId(box.id);
                allVerts.push(...wireframe);
                // Each line segment needs 2 vertices, each vertex needs a color
                for (let i = 0; i < wireframe.length / 3; i++) {
                    allColors.push(...color);
                }
                boxCentersRef.current.push({ id: box.id, center: box.center });
            }

            boxData.current = {
                verts: new Float32Array(allVerts),
                colors: new Float32Array(allColors),
                count: allVerts.length / 3,
            };
        } else {
            boxData.current = null;
            boxCentersRef.current = [];
        }

        // Build region geometry
        const regions = data.regions || [];
        regionData.current = [];
        for (let i = 0; i < regions.length; i++) {
            const region = regions[i];
            const verts = buildSolidCube(region.center, region.size);
            // Semi-transparent cyan for regions
            regionData.current.push({
                verts,
                color: [0.2, 0.6, 0.8, 0.15],
                count: verts.length / 3,
            });
        }

        // Update info
        const boxCount = boxes.length;
        const regionCount = regions.length;
        setInfo(`${p.n.toLocaleString()} pts | ${boxCount} people | ${regionCount} regions`);
    }, [data, fit]);

    // Render loop
    useEffect(() => {
        let id: number;
        const draw = () => {
            id = requestAnimationFrame(draw);
            const cv = canvasRef.current, bx = boxRef.current;
            if (!cv || !bx) return;

            let gl = glRef.current;
            if (!gl) {
                gl = cv.getContext("webgl", { antialias: true, alpha: false });
                if (!gl) return;
                glRef.current = gl;
            }

            // FPS
            fc.current++;
            const now = performance.now();
            if (now - lt.current >= 1000) { setFps(fc.current); fc.current = 0; lt.current = now; }

            const r = bx.getBoundingClientRect();
            const dpr = devicePixelRatio || 1;
            const w = Math.round(r.width * dpr), h = Math.round(r.height * dpr);
            if (!w || !h) return;
            if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }

            gl.viewport(0, 0, w, h);
            gl.clearColor(0.06, 0.06, 0.08, 1);
            gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
            gl.enable(gl.DEPTH_TEST);

            const g = gpu.current;
            if (!g) return;

            const c = cam.current;
            const cp = Math.cos(c.ph), sp = Math.sin(c.ph), ct = Math.cos(c.th), st = Math.sin(c.th);
            const eye = [c.tx + c.d * st * cp, c.ty + c.d * ct * cp, c.tz + c.d * sp * c.zUp];
            const view = m4Look(eye, [c.tx, c.ty, c.tz], [0, 0, c.zUp]);
            const proj = m4Persp(Math.PI / 4, w / h, c.d * 0.001, c.d * 10);
            const mvp = m4Mul(proj, view);

            // Draw point cloud
            const cm = cmRef.current;
            const cmi = cm === "height" ? 0 : cm === "signal" ? 1 : cm === "reflectivity" ? 2 : cm === "near_ir" ? 3 : 4;
            const rng = (cm === "solid") ? [0, 1] : (g.ranges[cm] || g.ranges.height || [0, 1]);

            gl.useProgram(g.pp);
            gl.uniformMatrix4fv(g.u.mvp, false, mvp);
            gl.uniform1f(g.u.ps, c.ps);
            gl.uniform1i(g.u.cm, cmi);
            gl.uniform2f(g.u.rng, rng[0], rng[1]);

            gl.enableVertexAttribArray(g.a.pos);
            gl.bindBuffer(gl.ARRAY_BUFFER, g.posBuf);
            gl.vertexAttribPointer(g.a.pos, 3, gl.FLOAT, false, 0, 0);

            gl.enableVertexAttribArray(g.a.h);
            gl.bindBuffer(gl.ARRAY_BUFFER, g.hBuf);
            gl.vertexAttribPointer(g.a.h, 1, gl.FLOAT, false, 0, 0);

            const bindField = (loc: number, key: string) => {
                if (loc < 0) return;
                if (g.fBufs[key]) {
                    gl.enableVertexAttribArray(loc);
                    gl.bindBuffer(gl.ARRAY_BUFFER, g.fBufs[key]);
                    gl.vertexAttribPointer(loc, 1, gl.FLOAT, false, 0, 0);
                } else {
                    gl.disableVertexAttribArray(loc);
                    gl.vertexAttrib1f(loc, 0);
                }
            };
            bindField(g.a.f1, "signal");
            bindField(g.a.f2, "reflectivity");
            bindField(g.a.f3, "near_ir");

            gl.drawArrays(gl.POINTS, 0, g.n);

            gl.disableVertexAttribArray(g.a.pos);
            gl.disableVertexAttribArray(g.a.h);
            if (g.a.f1 >= 0) gl.disableVertexAttribArray(g.a.f1);
            if (g.a.f2 >= 0) gl.disableVertexAttribArray(g.a.f2);
            if (g.a.f3 >= 0) gl.disableVertexAttribArray(g.a.f3);

            // Draw regions (transparent, so draw first)
            if (showRegions && regionData.current.length > 0) {
                gl.enable(gl.BLEND);
                gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
                gl.depthMask(false);

                gl.useProgram(g.rp);
                gl.uniformMatrix4fv(g.u.rmvp, false, mvp);

                for (const region of regionData.current) {
                    const buf = mkBuf(gl, region.verts);
                    gl.uniform4fv(g.u.rcolor, region.color);
                    gl.enableVertexAttribArray(g.a.rp);
                    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
                    gl.vertexAttribPointer(g.a.rp, 3, gl.FLOAT, false, 0, 0);
                    gl.drawArrays(gl.TRIANGLES, 0, region.count);
                    gl.disableVertexAttribArray(g.a.rp);
                    gl.deleteBuffer(buf);
                }

                gl.depthMask(true);
                gl.disable(gl.BLEND);
            }

            // Draw bounding boxes (wireframe)
            if (showBoxes && boxData.current) {
                gl.useProgram(g.lp);
                gl.uniformMatrix4fv(g.u.lmvp, false, mvp);

                const vBuf = mkBuf(gl, boxData.current.verts);
                const cBuf = mkBuf(gl, boxData.current.colors);

                gl.enableVertexAttribArray(g.a.lp);
                gl.bindBuffer(gl.ARRAY_BUFFER, vBuf);
                gl.vertexAttribPointer(g.a.lp, 3, gl.FLOAT, false, 0, 0);

                gl.enableVertexAttribArray(g.a.lc);
                gl.bindBuffer(gl.ARRAY_BUFFER, cBuf);
                gl.vertexAttribPointer(g.a.lc, 3, gl.FLOAT, false, 0, 0);

                gl.drawArrays(gl.LINES, 0, boxData.current.count);

                gl.disableVertexAttribArray(g.a.lp);
                gl.disableVertexAttribArray(g.a.lc);
                gl.deleteBuffer(vBuf);
                gl.deleteBuffer(cBuf);
            }

            // Draw axis
            gl.useProgram(g.lp);
            gl.uniformMatrix4fv(g.u.lmvp, false, mvp);
            gl.enableVertexAttribArray(g.a.lp);
            gl.bindBuffer(gl.ARRAY_BUFFER, g.axBuf);
            gl.vertexAttribPointer(g.a.lp, 3, gl.FLOAT, false, 0, 0);
            gl.enableVertexAttribArray(g.a.lc);
            gl.bindBuffer(gl.ARRAY_BUFFER, g.axCBuf);
            gl.vertexAttribPointer(g.a.lc, 3, gl.FLOAT, false, 0, 0);
            gl.drawArrays(gl.LINES, 0, 6);
            gl.disableVertexAttribArray(g.a.lp);
            gl.disableVertexAttribArray(g.a.lc);

            // Update screen positions for hover labels
            for (const box of boxCentersRef.current) {
                const [x, y, z] = box.center;
                const clip = new Float32Array(4);
                // Transform to clip space
                clip[0] = mvp[0] * x + mvp[4] * y + mvp[8] * z + mvp[12];
                clip[1] = mvp[1] * x + mvp[5] * y + mvp[9] * z + mvp[13];
                clip[2] = mvp[2] * x + mvp[6] * y + mvp[10] * z + mvp[14];
                clip[3] = mvp[3] * x + mvp[7] * y + mvp[11] * z + mvp[15];
                // Perspective divide and convert to screen coords
                if (clip[3] > 0) {
                    const ndcX = clip[0] / clip[3];
                    const ndcY = clip[1] / clip[3];
                    const screenX = (ndcX * 0.5 + 0.5) * r.width;
                    const screenY = (1 - (ndcY * 0.5 + 0.5)) * r.height;
                    box.screenPos = [screenX, screenY];
                }
            }
        };
        id = requestAnimationFrame(draw);
        return () => cancelAnimationFrame(id);
    }, [showBoxes, showRegions]);

    // Pointer interaction
    useEffect(() => {
        const cv = canvasRef.current; if (!cv) return;
        let drag = false, lx = 0, ly = 0;

        const down = (e: PointerEvent) => {
            if (e.button !== 0 && e.button !== 2) return;
            cv.setPointerCapture(e.pointerId);
            drag = true; lx = e.clientX; ly = e.clientY;
            e.preventDefault(); e.stopPropagation();
        };

        const move = (e: PointerEvent) => {
            // Check hover over box labels
            const rect = cv.getBoundingClientRect();
            const mx = e.clientX - rect.left;
            const my = e.clientY - rect.top;

            let foundLabel: { text: string; x: number; y: number } | null = null;
            for (const box of boxCentersRef.current) {
                if (box.screenPos) {
                    const [sx, sy] = box.screenPos;
                    const dist = Math.hypot(mx - sx, my - sy);
                    if (dist < 30) {
                        foundLabel = { text: `Person ${box.id}`, x: sx, y: sy - 20 };
                        break;
                    }
                }
            }
            setHoverLabel(foundLabel);

            if (!drag) return;
            const dx = e.clientX - lx, dy = e.clientY - ly;
            lx = e.clientX; ly = e.clientY;
            const c = cam.current;
            const eff: NavMode = (e.buttons & 2) ? "pan" : navRef.current;
            if (eff === "rotate") {
                c.th -= dx * 0.005 * c.zUp; c.ph += dy * 0.005;
                c.ph = Math.max(-Math.PI / 2 + .05, Math.min(Math.PI / 2 - .05, c.ph));
            } else if (eff === "pan") {
                const s = c.d * 0.002;
                const st = Math.sin(c.th), ct = Math.cos(c.th), sp = Math.sin(c.ph), cp = Math.cos(c.ph);
                const hdx = dx * c.zUp;
                c.tx += (ct * hdx + (-sp * st) * dy) * s;
                c.ty += (-st * hdx + (-sp * ct) * dy) * s;
                c.tz += cp * dy * s * c.zUp;
            } else {
                c.d *= 1 - dy * 0.005; c.d = Math.max(0.01, c.d);
            }
            e.stopPropagation();
        };

        const up = (e: PointerEvent) => { drag = false; cv.releasePointerCapture(e.pointerId); };
        const wheel = (e: WheelEvent) => {
            if (!hoverRef.current) return;
            e.preventDefault(); e.stopPropagation();
            cam.current.d *= e.deltaY > 0 ? 1.1 : 0.9;
            cam.current.d = Math.max(0.01, cam.current.d);
        };
        const ctx = (e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); };
        const enter = () => { hoverRef.current = true; };
        const leave = () => { hoverRef.current = false; setHoverLabel(null); };

        cv.addEventListener("pointerdown", down);
        cv.addEventListener("pointermove", move);
        cv.addEventListener("pointerup", up);
        cv.addEventListener("wheel", wheel, { passive: false });
        cv.addEventListener("contextmenu", ctx);
        cv.addEventListener("pointerenter", enter);
        cv.addEventListener("pointerleave", leave);
        return () => {
            cv.removeEventListener("pointerdown", down);
            cv.removeEventListener("pointermove", move);
            cv.removeEventListener("pointerup", up);
            cv.removeEventListener("wheel", wheel);
            cv.removeEventListener("contextmenu", ctx);
            cv.removeEventListener("pointerenter", enter);
            cv.removeEventListener("pointerleave", leave);
        };
    }, []);

    // Keyboard shortcuts
    useEffect(() => {
        const kd = (e: KeyboardEvent) => {
            if (!hoverRef.current) return;
            switch (e.key.toLowerCase()) {
                case "r": setNav("rotate"); break;
                case "g": setNav("pan"); break;
                case "z": setNav("zoom"); break;
                case "f": case "h": case "home": fit(); break;
                case "1": viewTop(); break;
                case "2": viewFront(); break;
                case "3": viewSide(); break;
                case "4": viewIso(); break;
                case "v": flipV(); break;
                case "[": cam.current.ps = Math.max(1, cam.current.ps - 1); break;
                case "]": cam.current.ps = Math.min(10, cam.current.ps + 1); break;
                case "b": setShowBoxes(b => !b); break;
                case "o": setShowRegions(r => !r); break;
                default: return;
            }
            e.preventDefault(); e.stopPropagation();
        };
        window.addEventListener("keydown", kd);
        return () => window.removeEventListener("keydown", kd);
    }, [fit, viewTop, viewFront, viewSide, viewIso, flipV]);

    // Available color modes
    const cloud = data.point_cloud;
    const hasF = (k: string) => !!(cloud?.fields_b64?.[k] || cloud?.fields?.[k]);
    const cms: { v: ColorMode; l: string }[] = [{ v: "height", l: "Height" }];
    if (hasF("signal")) cms.push({ v: "signal", l: "Signal" });
    if (hasF("reflectivity")) cms.push({ v: "reflectivity", l: "Reflect." });
    if (hasF("near_ir")) cms.push({ v: "near_ir", l: "Near IR" });
    cms.push({ v: "solid", l: "Solid" });

    // Build occupancy info display
    const regions = data.regions || [];
    const occupancy = data.occupancy || [];
    const occupancyDisplay = regions.map((r, i) => ({
        name: r.name,
        count: occupancy[i] ?? 0,
    }));

    return (
        <div ref={boxRef} style={{
            width: "100%", height: "100%", position: "relative",
            background: "#0e0e12", borderRadius: 4, overflow: "hidden",
        }}>
            {/* WebGL canvas */}
            <canvas ref={canvasRef} style={{
                position: "absolute", inset: 0,
                width: "100%", height: "100%",
                display: "block", touchAction: "none",
                zIndex: 0,
            }} />

            {/* Hover label */}
            {hoverLabel && (
                <div style={{
                    position: "absolute",
                    left: hoverLabel.x,
                    top: hoverLabel.y,
                    transform: "translate(-50%, -100%)",
                    background: "rgba(0,0,0,0.8)",
                    color: "#fff",
                    padding: "4px 8px",
                    borderRadius: 4,
                    fontSize: 12,
                    fontWeight: 600,
                    pointerEvents: "none",
                    zIndex: 20,
                    whiteSpace: "nowrap",
                }}>
                    {hoverLabel.text}
                </div>
            )}

            {/* UI Overlay */}
            <div style={{
                position: "absolute", inset: 0, zIndex: 10,
                pointerEvents: "none",
                display: "flex", flexDirection: "column",
                justifyContent: "space-between",
                padding: 6,
            }}>
                {/* TOP ROW */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    {/* Top-left: Color + Size + Visibility */}
                    <div style={{ display: "flex", gap: 4 }}>
                        <div style={{ ...panelStyle }}>
                            <select
                                value={colorMode}
                                onChange={(e) => setColorMode(e.target.value as ColorMode)}
                                onMouseDown={(e) => e.stopPropagation()}
                                onPointerDown={(e) => e.stopPropagation()}
                                style={{
                                    background: "rgba(0,0,0,0.4)", color: "#bbb",
                                    border: "1px solid rgba(255,255,255,0.1)", borderRadius: 4,
                                    padding: "3px 6px", fontSize: 11, cursor: "pointer",
                                    fontFamily: "'Inter','Segoe UI',system-ui,sans-serif",
                                    outline: "none", height: 26, pointerEvents: "auto",
                                }}
                            >
                                {cms.map(m => <option key={m.v} value={m.v}>{m.l}</option>)}
                            </select>
                            <TB label="−" tooltip="Smaller points [" compact onClick={() => { cam.current.ps = Math.max(1, cam.current.ps - 1); }} />
                            <TB label="+" tooltip="Larger points ]" compact onClick={() => { cam.current.ps = Math.min(10, cam.current.ps + 1); }} />
                        </div>
                        <div style={{ ...panelStyle }}>
                            <TB label="B" tooltip="Toggle Boxes [B]" active={showBoxes} onClick={() => setShowBoxes(b => !b)} compact />
                            <TB label="O" tooltip="Toggle Regions [O]" active={showRegions} onClick={() => setShowRegions(r => !r)} compact />
                        </div>
                    </div>
                    {/* Top-right: View presets */}
                    <div style={{ ...panelStyle }}>
                        <TB label="Top" tooltip="Top View [1]" onClick={viewTop} />
                        <TB label="Front" tooltip="Front View [2]" onClick={viewFront} />
                        <TB label="Side" tooltip="Side View [3]" onClick={viewSide} />
                        <TB label="Iso" tooltip="Isometric [4]" onClick={viewIso} />
                        <TB label="⇅" tooltip="Vertical Flip [V]" onClick={flipV} compact />
                    </div>
                </div>

                {/* BOTTOM ROW */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                    {/* Bottom-left: Nav modes + Fit */}
                    <div style={{ display: "flex", gap: 4 }}>
                        <div style={{ ...panelStyle }}>
                            <TB label="R" tooltip="Rotate [R]" active={nav === "rotate"} onClick={() => setNav("rotate")} compact />
                            <TB label="G" tooltip="Pan [G]" active={nav === "pan"} onClick={() => setNav("pan")} compact />
                            <TB label="Z" tooltip="Zoom [Z]" active={nav === "zoom"} onClick={() => setNav("zoom")} compact />
                        </div>
                        <div style={{ ...panelStyle }}>
                            <TB label="Fit" tooltip="Fit to view [F]" onClick={fit} />
                        </div>
                    </div>

                    {/* Bottom-center: Occupancy counts */}
                    {occupancyDisplay.length > 0 && (
                        <div style={{
                            ...panelStyle,
                            gap: 12,
                            padding: "4px 12px",
                        }}>
                            {occupancyDisplay.map((r, i) => (
                                <div key={i} style={{
                                    display: "flex",
                                    flexDirection: "column",
                                    alignItems: "center",
                                }}>
                                    <span style={{
                                        fontSize: 10,
                                        color: "rgba(150,150,170,0.7)",
                                        marginBottom: 2,
                                    }}>{r.name}</span>
                                    <span style={{
                                        fontSize: 18,
                                        fontWeight: 700,
                                        color: "#6cf",
                                    }}>{r.count}</span>
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Bottom-right: Stats */}
                    <div style={{
                        ...panelStyle,
                        gap: 8, padding: "3px 8px",
                        color: "rgba(180,180,200,0.6)", fontSize: 10,
                        fontFamily: "'JetBrains Mono','Fira Code',monospace",
                    }}>
                        <span>{info}</span>
                        <span style={{ color: "rgba(120,200,120,0.5)" }}>{fpsVal} fps</span>
                    </div>
                </div>
            </div>
        </div>
    );
};
