import React, { useRef, useEffect, useCallback, useState, memo } from "react";

// ═══════════════════════════════════════════════════════════════════════════
// DATA TYPES
// ═══════════════════════════════════════════════════════════════════════════
interface PointCloudData {
    _type: "PointCloud";
    num_points: number;
    positions_b64?: string;                   // base64 Float32 (preferred)
    fields_b64?: Record<string, string>;      // base64 Float32 per field
    positions?: number[][];                   // legacy nested
    fields?: Record<string, number[]>;        // legacy nested
    metadata?: Record<string, unknown>;
}

interface Props { data: PointCloudData; }

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

// ═══════════════════════════════════════════════════════════════════════════
// UI COMPONENTS  (defined OUTSIDE the main component to prevent remounting)
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
        onMouseDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
        }}
        onPointerDown={(e) => {
            e.stopPropagation();
            e.preventDefault();
        }}
        onClick={(e) => {
            e.stopPropagation();
            e.preventDefault();
            onClick();
        }}
    >{label}</button>
));

// ═══════════════════════════════════════════════════════════════════════════
// SHADERS — GPU turbo colormap
// ═══════════════════════════════════════════════════════════════════════════
const POINT_VS = `
attribute vec3 a_pos;
attribute float a_h;    // height (z)
attribute float a_f1;   // signal
attribute float a_f2;   // reflectivity
attribute float a_f3;   // near_ir

uniform mat4 u_mvp;
uniform float u_ps;      // point size
uniform int u_cm;        // color mode: 0=height 1=signal 2=reflect 3=near_ir 4=solid
uniform vec2 u_range;    // (min, max) of active field

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
// DATA PARSER
// ═══════════════════════════════════════════════════════════════════════════
interface Parsed {
    pos: Float32Array;
    h: Float32Array;
    fields: Record<string, Float32Array>;
    n: number;
    bounds: { min: [number, number, number]; max: [number, number, number] };
}

function parse(d: PointCloudData): Parsed | null {
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
export const PointCloudWidget: React.FC<Props> = ({ data }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const boxRef = useRef<HTMLDivElement>(null);
    const glRef = useRef<WebGLRenderingContext | null>(null);
    const hoverRef = useRef(false);

    const cam = useRef({ th: Math.PI / 4, ph: Math.PI / 6, d: 50, tx: 0, ty: 0, tz: 0, ps: 2 });

    const [colorMode, setColorMode] = useState<ColorMode>("height");
    const [nav, setNav] = useState<NavMode>("rotate");
    const [info, setInfo] = useState("");
    const [fpsVal, setFps] = useState(0);

    const navRef = useRef<NavMode>(nav);
    navRef.current = nav;
    const cmRef = useRef<ColorMode>(colorMode);
    cmRef.current = colorMode;

    const gpu = useRef<{
        pp: WebGLProgram; lp: WebGLProgram;
        posBuf: WebGLBuffer; hBuf: WebGLBuffer;
        fBufs: Record<string, WebGLBuffer>;
        axBuf: WebGLBuffer; axCBuf: WebGLBuffer;
        n: number;
        bounds: Parsed["bounds"];
        ranges: Record<string, [number, number]>;
        u: Record<string, WebGLUniformLocation | null>;
        a: Record<string, number>;
    } | null>(null);

    const fitted = useRef(false);
    const fc = useRef(0);
    const lt = useRef(performance.now());

    // ── Camera control ───────────────────────────────────────────────────
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

    // ── Data upload ──────────────────────────────────────────────────────
    useEffect(() => {
        const cv = canvasRef.current;
        if (!cv || !data || data._type !== "PointCloud" || !data.num_points) return;
        const p = parse(data); if (!p) return;

        let gl = glRef.current;
        if (!gl) { gl = cv.getContext("webgl", { antialias: true, alpha: false }); if (!gl) return; glRef.current = gl; }

        let pp: WebGLProgram, lp: WebGLProgram;
        if (gpu.current) {
            pp = gpu.current.pp; lp = gpu.current.lp;
            gl.deleteBuffer(gpu.current.posBuf); gl.deleteBuffer(gpu.current.hBuf);
            for (const b of Object.values(gpu.current.fBufs)) gl.deleteBuffer(b);
            gl.deleteBuffer(gpu.current.axBuf); gl.deleteBuffer(gpu.current.axCBuf);
        } else {
            pp = mkProg(gl, POINT_VS, POINT_FS);
            lp = mkProg(gl, LINE_VS, LINE_FS);
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
        };
        const a: Record<string, number> = {
            pos: gl.getAttribLocation(pp, "a_pos"),
            h: gl.getAttribLocation(pp, "a_h"),
            f1: gl.getAttribLocation(pp, "a_f1"),
            f2: gl.getAttribLocation(pp, "a_f2"),
            f3: gl.getAttribLocation(pp, "a_f3"),
            lp: gl.getAttribLocation(lp, "a_pos"),
            lc: gl.getAttribLocation(lp, "a_col"),
        };

        gpu.current = { pp, lp, posBuf, hBuf, fBufs, axBuf, axCBuf, n: p.n, bounds: p.bounds, ranges, u, a };

        if (!fitted.current) { fit(); fitted.current = true; }
        setInfo(`${p.n.toLocaleString()} pts`);
    }, [data, fit]);

    // ── Render loop ──────────────────────────────────────────────────────
    useEffect(() => {
        let id: number;
        const draw = () => {
            id = requestAnimationFrame(draw);
            const gl = glRef.current, g = gpu.current, cv = canvasRef.current, bx = boxRef.current;
            if (!gl || !g || !cv || !bx) return;

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

            const c = cam.current;
            const cp = Math.cos(c.ph), sp = Math.sin(c.ph), ct = Math.cos(c.th), st = Math.sin(c.th);
            const eye = [c.tx + c.d * st * cp, c.ty + c.d * ct * cp, c.tz + c.d * sp];
            const view = m4Look(eye, [c.tx, c.ty, c.tz], [0, 0, 1]);
            const proj = m4Persp(Math.PI / 4, w / h, c.d * 0.001, c.d * 10);
            const mvp = m4Mul(proj, view);

            // Color mode
            const cm = cmRef.current;
            const cmi = cm === "height" ? 0 : cm === "signal" ? 1 : cm === "reflectivity" ? 2 : cm === "near_ir" ? 3 : 4;
            const rng = (cm === "solid") ? [0, 1] : (g.ranges[cm] || g.ranges.height || [0, 1]);

            gl.useProgram(g.pp);
            gl.uniformMatrix4fv(g.u.mvp, false, mvp);
            gl.uniform1f(g.u.ps, c.ps);
            gl.uniform1i(g.u.cm, cmi);
            gl.uniform2f(g.u.rng, rng[0], rng[1]);

            // Bind attributes
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

            // Axis
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
        };
        draw();
        return () => cancelAnimationFrame(id);
    }, []);

    // ── Pointer interaction on CANVAS only ───────────────────────────────
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
            if (!drag) return;
            const dx = e.clientX - lx, dy = e.clientY - ly;
            lx = e.clientX; ly = e.clientY;
            const c = cam.current;
            const eff: NavMode = (e.buttons & 2) ? "pan" : navRef.current;
            if (eff === "rotate") {
                c.th -= dx * 0.005; c.ph += dy * 0.005;
                c.ph = Math.max(-Math.PI / 2 + .05, Math.min(Math.PI / 2 - .05, c.ph));
            } else if (eff === "pan") {
                const s = c.d * 0.002;
                const st = Math.sin(c.th), ct = Math.cos(c.th), sp = Math.sin(c.ph), cp = Math.cos(c.ph);
                c.tx += (ct * dx + (-sp * st) * dy) * s;
                c.ty += (-st * dx + (-sp * ct) * dy) * s;
                c.tz += cp * dy * s;
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
        const leave = () => { hoverRef.current = false; };

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

    // ── Keyboard shortcuts ───────────────────────────────────────────────
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
                case "[": cam.current.ps = Math.max(1, cam.current.ps - 1); break;
                case "]": cam.current.ps = Math.min(10, cam.current.ps + 1); break;
                default: return;
            }
            e.preventDefault(); e.stopPropagation();
        };
        window.addEventListener("keydown", kd);
        return () => window.removeEventListener("keydown", kd);
    }, [fit, viewTop, viewFront, viewSide, viewIso]);

    // ── Available color modes ────────────────────────────────────────────
    const hasF = (k: string) => !!(data.fields_b64?.[k] || data.fields?.[k]);
    const cms: { v: ColorMode; l: string }[] = [{ v: "height", l: "Height" }];
    if (hasF("signal")) cms.push({ v: "signal", l: "Signal" });
    if (hasF("reflectivity")) cms.push({ v: "reflectivity", l: "Reflect." });
    if (hasF("near_ir")) cms.push({ v: "near_ir", l: "Near IR" });
    cms.push({ v: "solid", l: "Solid" });

    // ═════════════════════════════════════════════════════════════════════
    // RENDER
    // ═════════════════════════════════════════════════════════════════════
    return (
        <div ref={boxRef} style={{
            width: "100%", height: "100%", position: "relative",
            background: "#0e0e12", borderRadius: 4, overflow: "hidden",
        }}>
            {/* WebGL canvas — z-index 0 */}
            <canvas ref={canvasRef} style={{
                position: "absolute", inset: 0,
                width: "100%", height: "100%",
                display: "block", touchAction: "none",
                zIndex: 0,
            }} />

            {/* ── UI OVERLAY — z-index 10, pointer-events: none container ── */}
            <div style={{
                position: "absolute", inset: 0, zIndex: 10,
                pointerEvents: "none",
                display: "flex", flexDirection: "column",
                justifyContent: "space-between",
                padding: 6,
            }}>
                {/* TOP ROW */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    {/* Top-left: Color + Size */}
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
                                outline: "none", height: 26,
                                pointerEvents: "auto",
                            }}
                        >
                            {cms.map(m => <option key={m.v} value={m.v}>{m.l}</option>)}
                        </select>
                        <TB label="−" tooltip="Smaller points  [ [ ]" compact onClick={() => { cam.current.ps = Math.max(1, cam.current.ps - 1); }} />
                        <TB label="+" tooltip="Larger points  [ ] ]" compact onClick={() => { cam.current.ps = Math.min(10, cam.current.ps + 1); }} />
                    </div>
                    {/* Top-right: View presets */}
                    <div style={{ ...panelStyle }}>
                        <TB label="Top" tooltip="Top View  [1]" onClick={viewTop} />
                        <TB label="Front" tooltip="Front View  [2]" onClick={viewFront} />
                        <TB label="Side" tooltip="Side View  [3]" onClick={viewSide} />
                        <TB label="Iso" tooltip="Isometric  [4]" onClick={viewIso} />
                    </div>
                </div>

                {/* BOTTOM ROW */}
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
                    {/* Bottom-left: Nav modes + Fit */}
                    <div style={{ display: "flex", gap: 4 }}>
                        <div style={{ ...panelStyle }}>
                            <TB label="R" tooltip="Rotate  [R]" active={nav === "rotate"} onClick={() => setNav("rotate")} compact />
                            <TB label="G" tooltip="Pan  [G]" active={nav === "pan"} onClick={() => setNav("pan")} compact />
                            <TB label="Z" tooltip="Zoom  [Z]" active={nav === "zoom"} onClick={() => setNav("zoom")} compact />
                        </div>
                        <div style={{ ...panelStyle }}>
                            <TB label="Fit" tooltip="Fit to view  [F]" onClick={fit} />
                        </div>
                    </div>
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
