import React, { useRef, useEffect, useCallback, useState } from "react";

interface PointCloudData {
    _type: "PointCloud";
    num_points: number;
    positions: number[][];
    fields?: Record<string, number[]>;
    metadata?: Record<string, unknown>;
}

interface Props {
    data: PointCloudData;
}

type ColorMode = "height" | "intensity" | "reflectivity" | "solid";
type InteractionMode = "rotate" | "pan" | "zoom";

function turboColormap(t: number): [number, number, number] {
    t = Math.max(0, Math.min(1, t));
    const r = Math.max(0, Math.min(1, 0.13572 + t * (4.6153 + t * (-42.66 + t * (132.13 + t * (-152.95 + t * 56.67))))));
    const g = Math.max(0, Math.min(1, 0.09140 + t * (2.1643 + t * (4.8428 + t * (-27.66 + t * (29.04 + t * (-8.36)))))));
    const b = Math.max(0, Math.min(1, 0.10667 + t * (12.486 + t * (-60.46 + t * (109.98 + t * (-89.09 + t * 25.79))))));
    return [r, g, b];
}

// ── Shaders ──────────────────────────────────────────────────────────────
const VERT_SRC = `
attribute vec3 a_position;
attribute vec3 a_color;
uniform mat4 u_mvp;
uniform float u_pointSize;
varying vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(a_position, 1.0);
    gl_PointSize = u_pointSize;
    v_color = a_color;
}
`;

const FRAG_SRC = `
precision mediump float;
varying vec3 v_color;
void main() {
    vec2 c = gl_PointCoord - vec2(0.5);
    if (dot(c, c) > 0.25) discard;
    gl_FragColor = vec4(v_color, 1.0);
}
`;

const LINE_VERT = `
attribute vec3 a_position;
attribute vec3 a_color;
uniform mat4 u_mvp;
varying vec3 v_color;
void main() {
    gl_Position = u_mvp * vec4(a_position, 1.0);
    v_color = a_color;
}
`;
const LINE_FRAG = `
precision mediump float;
varying vec3 v_color;
void main() { gl_FragColor = vec4(v_color, 1.0); }
`;

// ── Matrix helpers (column-major for WebGL) ──────────────────────────────

function mat4Multiply(a: Float32Array, b: Float32Array): Float32Array {
    const o = new Float32Array(16);
    for (let c = 0; c < 4; c++)
        for (let r = 0; r < 4; r++)
            o[c * 4 + r] =
                a[0 * 4 + r] * b[c * 4 + 0] +
                a[1 * 4 + r] * b[c * 4 + 1] +
                a[2 * 4 + r] * b[c * 4 + 2] +
                a[3 * 4 + r] * b[c * 4 + 3];
    return o;
}

function mat4Perspective(fov: number, aspect: number, near: number, far: number): Float32Array {
    const m = new Float32Array(16);
    const f = 1 / Math.tan(fov / 2);
    m[0] = f / aspect;
    m[5] = f;
    m[10] = (far + near) / (near - far);
    m[11] = -1;
    m[14] = (2 * far * near) / (near - far);
    return m;
}

function mat4LookAt(eye: number[], center: number[], up: number[]): Float32Array {
    let fx = eye[0] - center[0], fy = eye[1] - center[1], fz = eye[2] - center[2];
    let len = Math.sqrt(fx * fx + fy * fy + fz * fz) || 1;
    fx /= len; fy /= len; fz /= len;

    let rx = up[1] * fz - up[2] * fy;
    let ry = up[2] * fx - up[0] * fz;
    let rz = up[0] * fy - up[1] * fx;
    len = Math.sqrt(rx * rx + ry * ry + rz * rz) || 1;
    rx /= len; ry /= len; rz /= len;

    const ux = fy * rz - fz * ry;
    const uy = fz * rx - fx * rz;
    const uz = fx * ry - fy * rx;

    const m = new Float32Array(16);
    m[0] = rx;  m[1] = ux;  m[2] = fx;  m[3] = 0;
    m[4] = ry;  m[5] = uy;  m[6] = fy;  m[7] = 0;
    m[8] = rz;  m[9] = uz;  m[10] = fz; m[11] = 0;
    m[12] = -(rx * eye[0] + ry * eye[1] + rz * eye[2]);
    m[13] = -(ux * eye[0] + uy * eye[1] + uz * eye[2]);
    m[14] = -(fx * eye[0] + fy * eye[1] + fz * eye[2]);
    m[15] = 1;
    return m;
}

// ── WebGL helpers ────────────────────────────────────────────────────────
function compileShader(gl: WebGLRenderingContext, src: string, type: number): WebGLShader {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    if (!gl.getShaderParameter(s, gl.COMPILE_STATUS))
        throw new Error(gl.getShaderInfoLog(s) || "shader compile error");
    return s;
}

function linkProgram(gl: WebGLRenderingContext, vs: string, fs: string): WebGLProgram {
    const p = gl.createProgram()!;
    gl.attachShader(p, compileShader(gl, vs, gl.VERTEX_SHADER));
    gl.attachShader(p, compileShader(gl, fs, gl.FRAGMENT_SHADER));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS))
        throw new Error(gl.getProgramInfoLog(p) || "link error");
    return p;
}

// ═════════════════════════════════════════════════════════════════════════
export const PointCloudWidget: React.FC<Props> = ({ data }) => {
    const canvasRef = useRef<HTMLCanvasElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);
    const glRef = useRef<WebGLRenderingContext | null>(null);
    const hoveredRef = useRef(false);

    const cameraRef = useRef({
        theta: Math.PI / 4,
        phi: Math.PI / 6,
        distance: 50,
        targetX: 0,
        targetY: 0,
        targetZ: 0,
        pointSize: 2.0,
    });

    // Store initial camera for reset
    const initialCamRef = useRef<typeof cameraRef.current | null>(null);

    const [colorMode, setColorMode] = useState<ColorMode>("height");
    const [mode, setMode] = useState<InteractionMode>("rotate");
    const [info, setInfo] = useState("");

    // Expose mode to pointer handler via ref
    const modeRef = useRef<InteractionMode>(mode);
    modeRef.current = mode;

    const gpuRef = useRef<{
        program: WebGLProgram;
        lineProgram: WebGLProgram;
        posBuf: WebGLBuffer;
        colBuf: WebGLBuffer;
        axisBuf: WebGLBuffer;
        axisColBuf: WebGLBuffer;
        numPoints: number;
        bounds: { min: number[]; max: number[] };
    } | null>(null);

    const fittedRef = useRef(false);

    // ── Fit camera to bounds ─────────────────────────────────────────────
    const fitCamera = useCallback(() => {
        const gpu = gpuRef.current;
        if (!gpu) return;
        const { min, max } = gpu.bounds;
        const cam = cameraRef.current;
        cam.targetX = (min[0] + max[0]) / 2;
        cam.targetY = (min[1] + max[1]) / 2;
        cam.targetZ = (min[2] + max[2]) / 2;
        cam.distance = Math.max(max[0] - min[0], max[1] - min[1], max[2] - min[2], 1) * 1.5;
        cam.theta = Math.PI / 4;
        cam.phi = Math.PI / 6;
    }, []);

    // ── Build GPU buffers ────────────────────────────────────────────────
    const buildBuffers = useCallback((gl: WebGLRenderingContext, cloud: PointCloudData, cMode: ColorMode) => {
        const N = cloud.num_points;
        if (N === 0) return null;

        const positions = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            const p = cloud.positions[i];
            positions[i * 3] = p[0];
            positions[i * 3 + 1] = p[1];
            positions[i * 3 + 2] = p[2];
        }

        let minX = Infinity, minY = Infinity, minZ = Infinity;
        let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity;
        for (let i = 0; i < N; i++) {
            const x = positions[i * 3], y = positions[i * 3 + 1], z = positions[i * 3 + 2];
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (y < minY) minY = y; if (y > maxY) maxY = y;
            if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
        }
        const bounds = { min: [minX, minY, minZ], max: [maxX, maxY, maxZ] };

        const fields: Record<string, Float32Array> = {};
        if (cloud.fields) {
            for (const [k, arr] of Object.entries(cloud.fields))
                fields[k] = new Float32Array(arr);
        }

        const heightRange = (maxZ - minZ) || 1;
        let fMin = 0, fMax = 1;
        const activeField = cMode === "intensity" ? fields.signal : cMode === "reflectivity" ? fields.reflectivity : null;
        if (activeField) {
            fMin = Infinity; fMax = -Infinity;
            for (let i = 0; i < N; i++) {
                if (activeField[i] < fMin) fMin = activeField[i];
                if (activeField[i] > fMax) fMax = activeField[i];
            }
            if (fMax === fMin) fMax = fMin + 1;
        }

        const colors = new Float32Array(N * 3);
        for (let i = 0; i < N; i++) {
            let t = 0;
            if (cMode === "height") {
                t = (positions[i * 3 + 2] - minZ) / heightRange;
            } else if (activeField) {
                t = (activeField[i] - fMin) / (fMax - fMin);
            }
            const [r, g, b] = cMode === "solid" ? [0.2, 0.7, 1.0] as const : turboColormap(t);
            colors[i * 3] = r; colors[i * 3 + 1] = g; colors[i * 3 + 2] = b;
        }

        const posBuf = gl.createBuffer()!;
        gl.bindBuffer(gl.ARRAY_BUFFER, posBuf);
        gl.bufferData(gl.ARRAY_BUFFER, positions, gl.STATIC_DRAW);

        const colBuf = gl.createBuffer()!;
        gl.bindBuffer(gl.ARRAY_BUFFER, colBuf);
        gl.bufferData(gl.ARRAY_BUFFER, colors, gl.STATIC_DRAW);

        const extent = Math.max(maxX - minX, maxY - minY, maxZ - minZ) || 10;
        const axLen = extent * 0.08;
        const cx = (minX + maxX) / 2, cy = (minY + maxY) / 2;
        const axisVerts = new Float32Array([
            cx, cy, minZ, cx + axLen, cy, minZ,
            cx, cy, minZ, cx, cy + axLen, minZ,
            cx, cy, minZ, cx, cy, minZ + axLen,
        ]);
        const axisColors = new Float32Array([
            1, 0.2, 0.2, 1, 0.2, 0.2,
            0.2, 1, 0.2, 0.2, 1, 0.2,
            0.3, 0.5, 1, 0.3, 0.5, 1,
        ]);

        const axisBuf = gl.createBuffer()!;
        gl.bindBuffer(gl.ARRAY_BUFFER, axisBuf);
        gl.bufferData(gl.ARRAY_BUFFER, axisVerts, gl.STATIC_DRAW);

        const axisColBuf = gl.createBuffer()!;
        gl.bindBuffer(gl.ARRAY_BUFFER, axisColBuf);
        gl.bufferData(gl.ARRAY_BUFFER, axisColors, gl.STATIC_DRAW);

        return { posBuf, colBuf, axisBuf, axisColBuf, numPoints: N, bounds };
    }, []);

    // ── Init WebGL + upload data ─────────────────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas || !data || data._type !== "PointCloud" || data.num_points === 0) return;

        let gl = glRef.current;
        if (!gl) {
            gl = canvas.getContext("webgl", { antialias: true, alpha: false });
            if (!gl) return;
            glRef.current = gl;
        }

        let program: WebGLProgram;
        let lineProgram: WebGLProgram;
        if (gpuRef.current) {
            program = gpuRef.current.program;
            lineProgram = gpuRef.current.lineProgram;
            gl.deleteBuffer(gpuRef.current.posBuf);
            gl.deleteBuffer(gpuRef.current.colBuf);
            gl.deleteBuffer(gpuRef.current.axisBuf);
            gl.deleteBuffer(gpuRef.current.axisColBuf);
        } else {
            program = linkProgram(gl, VERT_SRC, FRAG_SRC);
            lineProgram = linkProgram(gl, LINE_VERT, LINE_FRAG);
        }

        const bufs = buildBuffers(gl, data, colorMode);
        if (!bufs) return;

        gpuRef.current = { program, lineProgram, ...bufs };

        if (!fittedRef.current) {
            fitCamera();
            // Save initial camera state for Home reset
            initialCamRef.current = { ...cameraRef.current };
            fittedRef.current = true;
        }

        setInfo(`${bufs.numPoints.toLocaleString()} pts`);
    }, [data, colorMode, buildBuffers, fitCamera]);

    // ── Render loop ──────────────────────────────────────────────────────
    useEffect(() => {
        let animId: number;
        const render = () => {
            animId = requestAnimationFrame(render);
            const gl = glRef.current;
            const gpu = gpuRef.current;
            const canvas = canvasRef.current;
            const container = containerRef.current;
            if (!gl || !gpu || !canvas || !container) return;

            const rect = container.getBoundingClientRect();
            const dpr = window.devicePixelRatio || 1;
            const w = Math.round(rect.width * dpr);
            const h = Math.round(rect.height * dpr);
            if (w === 0 || h === 0) return;
            if (canvas.width !== w || canvas.height !== h) {
                canvas.width = w; canvas.height = h;
            }

            gl.viewport(0, 0, w, h);
            gl.clearColor(0.08, 0.08, 0.1, 1);
            gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
            gl.enable(gl.DEPTH_TEST);

            const cam = cameraRef.current;
            const cosP = Math.cos(cam.phi), sinP = Math.sin(cam.phi);
            const cosT = Math.cos(cam.theta), sinT = Math.sin(cam.theta);
            const eyeX = cam.targetX + cam.distance * sinT * cosP;
            const eyeY = cam.targetY + cam.distance * cosT * cosP;
            const eyeZ = cam.targetZ + cam.distance * sinP;

            const view = mat4LookAt([eyeX, eyeY, eyeZ], [cam.targetX, cam.targetY, cam.targetZ], [0, 0, 1]);
            const proj = mat4Perspective(Math.PI / 4, w / h, cam.distance * 0.001, cam.distance * 10);
            const mvp = mat4Multiply(proj, view);

            // Points
            gl.useProgram(gpu.program);
            gl.uniformMatrix4fv(gl.getUniformLocation(gpu.program, "u_mvp"), false, mvp);
            gl.uniform1f(gl.getUniformLocation(gpu.program, "u_pointSize"), cam.pointSize);

            const aPos = gl.getAttribLocation(gpu.program, "a_position");
            const aCol = gl.getAttribLocation(gpu.program, "a_color");

            gl.enableVertexAttribArray(aPos);
            gl.bindBuffer(gl.ARRAY_BUFFER, gpu.posBuf);
            gl.vertexAttribPointer(aPos, 3, gl.FLOAT, false, 0, 0);
            gl.enableVertexAttribArray(aCol);
            gl.bindBuffer(gl.ARRAY_BUFFER, gpu.colBuf);
            gl.vertexAttribPointer(aCol, 3, gl.FLOAT, false, 0, 0);
            gl.drawArrays(gl.POINTS, 0, gpu.numPoints);
            gl.disableVertexAttribArray(aPos);
            gl.disableVertexAttribArray(aCol);

            // Axis lines
            gl.useProgram(gpu.lineProgram);
            gl.uniformMatrix4fv(gl.getUniformLocation(gpu.lineProgram, "u_mvp"), false, mvp);

            const lPos = gl.getAttribLocation(gpu.lineProgram, "a_position");
            const lCol = gl.getAttribLocation(gpu.lineProgram, "a_color");
            gl.enableVertexAttribArray(lPos);
            gl.bindBuffer(gl.ARRAY_BUFFER, gpu.axisBuf);
            gl.vertexAttribPointer(lPos, 3, gl.FLOAT, false, 0, 0);
            gl.enableVertexAttribArray(lCol);
            gl.bindBuffer(gl.ARRAY_BUFFER, gpu.axisColBuf);
            gl.vertexAttribPointer(lCol, 3, gl.FLOAT, false, 0, 0);
            gl.drawArrays(gl.LINES, 0, 6);
            gl.disableVertexAttribArray(lPos);
            gl.disableVertexAttribArray(lCol);
        };
        render();
        return () => cancelAnimationFrame(animId);
    }, []);

    // ── Pointer interaction ──────────────────────────────────────────────
    useEffect(() => {
        const canvas = canvasRef.current;
        if (!canvas) return;

        let active = false;
        let lastX = 0, lastY = 0;

        const onPointerDown = (e: PointerEvent) => {
            if (e.button !== 0 && e.button !== 2) return;
            canvas.setPointerCapture(e.pointerId);
            active = true;
            lastX = e.clientX; lastY = e.clientY;
            e.preventDefault();
            e.stopPropagation();
        };

        const onPointerMove = (e: PointerEvent) => {
            if (!active) return;
            const dx = e.clientX - lastX;
            const dy = e.clientY - lastY;
            lastX = e.clientX; lastY = e.clientY;
            const cam = cameraRef.current;

            // Right-click always pans regardless of mode
            const effectiveMode: InteractionMode = (e.buttons & 2) ? "pan" : modeRef.current;

            if (effectiveMode === "rotate") {
                cam.theta -= dx * 0.005;
                cam.phi += dy * 0.005;
                cam.phi = Math.max(-Math.PI / 2 + 0.05, Math.min(Math.PI / 2 - 0.05, cam.phi));
            } else if (effectiveMode === "pan") {
                const panScale = cam.distance * 0.002;
                const sinT = Math.sin(cam.theta), cosT = Math.cos(cam.theta);
                const sinP = Math.sin(cam.phi), cosP = Math.cos(cam.phi);
                // Camera right vector (horizontal)
                const rx = -cosT, ry = sinT;
                // Camera up vector (accounts for elevation angle)
                const ux = -sinP * sinT, uy = -sinP * cosT, uz = cosP;
                cam.targetX += (-rx * dx + ux * dy) * panScale;
                cam.targetY += (-ry * dx + uy * dy) * panScale;
                cam.targetZ += uz * dy * panScale;
            } else if (effectiveMode === "zoom") {
                cam.distance *= 1 - dy * 0.005;
                cam.distance = Math.max(0.01, cam.distance);
            }
            e.stopPropagation();
        };

        const onPointerUp = (e: PointerEvent) => {
            active = false;
            canvas.releasePointerCapture(e.pointerId);
        };

        const onWheel = (e: WheelEvent) => {
            if (!hoveredRef.current) return;
            e.preventDefault();
            e.stopPropagation();
            const cam = cameraRef.current;
            cam.distance *= e.deltaY > 0 ? 1.1 : 0.9;
            cam.distance = Math.max(0.01, cam.distance);
        };

        const onContext = (e: MouseEvent) => { e.preventDefault(); e.stopPropagation(); };
        const onEnter = () => { hoveredRef.current = true; };
        const onLeave = () => { hoveredRef.current = false; };

        canvas.addEventListener("pointerdown", onPointerDown);
        canvas.addEventListener("pointermove", onPointerMove);
        canvas.addEventListener("pointerup", onPointerUp);
        canvas.addEventListener("wheel", onWheel, { passive: false });
        canvas.addEventListener("contextmenu", onContext);
        canvas.addEventListener("pointerenter", onEnter);
        canvas.addEventListener("pointerleave", onLeave);

        return () => {
            canvas.removeEventListener("pointerdown", onPointerDown);
            canvas.removeEventListener("pointermove", onPointerMove);
            canvas.removeEventListener("pointerup", onPointerUp);
            canvas.removeEventListener("wheel", onWheel);
            canvas.removeEventListener("contextmenu", onContext);
            canvas.removeEventListener("pointerenter", onEnter);
            canvas.removeEventListener("pointerleave", onLeave);
        };
    }, []);

    // ── Keyboard shortcuts (active when hovered) ─────────────────────────
    useEffect(() => {
        const onKeyDown = (e: KeyboardEvent) => {
            if (!hoveredRef.current) return;
            const key = e.key.toLowerCase();
            switch (key) {
                case "r": setMode("rotate"); break;
                case "g": setMode("pan"); break;
                case "z": setMode("zoom"); break;
                case "f": case "home": case "h": fitCamera(); break;
                case "[": cameraRef.current.pointSize = Math.max(1, cameraRef.current.pointSize - 1); break;
                case "]": cameraRef.current.pointSize = Math.min(10, cameraRef.current.pointSize + 1); break;
                default: return;
            }
            e.preventDefault();
            e.stopPropagation();
        };
        window.addEventListener("keydown", onKeyDown);
        return () => window.removeEventListener("keydown", onKeyDown);
    }, [fitCamera]);

    // ── Color mode options ───────────────────────────────────────────────
    const colorModes: { value: ColorMode; label: string }[] = [
        { value: "height", label: "Height" },
    ];
    if (data.fields?.signal) colorModes.push({ value: "intensity", label: "Signal" });
    if (data.fields?.reflectivity) colorModes.push({ value: "reflectivity", label: "Reflect." });
    colorModes.push({ value: "solid", label: "Solid" });

    // ── Toolbar button helper ────────────────────────────────────────────
    const ToolBtn = ({ label, tooltip, active, onClick }: {
        label: string; tooltip: string; active?: boolean; onClick: () => void;
    }) => (
        <button
            onClick={onClick}
            onPointerDown={(e) => e.stopPropagation()}
            title={tooltip}
            style={{
                ...tbStyle,
                background: active ? "rgba(80,140,255,0.35)" : "rgba(0,0,0,0.5)",
                border: active ? "1px solid rgba(80,140,255,0.6)" : "1px solid #444",
                color: active ? "#9fc5ff" : "#aaa",
            }}
        >{label}</button>
    );

    return (
        <div
            ref={containerRef}
            style={{
                width: "100%", height: "100%", position: "relative",
                background: "#14141a", borderRadius: 4, overflow: "hidden",
            }}
        >
            <canvas
                ref={canvasRef}
                style={{ width: "100%", height: "100%", display: "block", touchAction: "none" }}
            />

            {/* ── Top-left: Color mode + Point size ── */}
            <div style={{ position: "absolute", top: 6, left: 8, display: "flex", gap: 4, alignItems: "center" }}>
                <select
                    value={colorMode}
                    onChange={(e) => setColorMode(e.target.value as ColorMode)}
                    onPointerDown={(e) => e.stopPropagation()}
                    style={{
                        background: "rgba(0,0,0,0.6)", color: "#ccc",
                        border: "1px solid #555", borderRadius: 3,
                        padding: "2px 4px", fontSize: 11, cursor: "pointer",
                    }}
                >
                    {colorModes.map((m) => (
                        <option key={m.value} value={m.value}>{m.label}</option>
                    ))}
                </select>

                <button onClick={() => { cameraRef.current.pointSize = Math.max(1, cameraRef.current.pointSize - 1); }}
                    onPointerDown={(e) => e.stopPropagation()} style={tbStyle} title="Decrease point size  [ [ ]">-</button>
                <button onClick={() => { cameraRef.current.pointSize = Math.min(10, cameraRef.current.pointSize + 1); }}
                    onPointerDown={(e) => e.stopPropagation()} style={tbStyle} title="Increase point size  [ ] ]">+</button>
            </div>

            {/* ── Left toolbar: Interaction modes ── */}
            <div style={{
                position: "absolute", top: 36, left: 8,
                display: "flex", flexDirection: "column", gap: 3,
            }}>
                <ToolBtn label="R" tooltip="Rotate  [R]" active={mode === "rotate"} onClick={() => setMode("rotate")} />
                <ToolBtn label="G" tooltip="Grab / Pan  [G]" active={mode === "pan"} onClick={() => setMode("pan")} />
                <ToolBtn label="Z" tooltip="Zoom  [Z]" active={mode === "zoom"} onClick={() => setMode("zoom")} />
                <div style={{ height: 4 }} />
                <ToolBtn label="F" tooltip="Fit to view  [F]" onClick={fitCamera} />
            </div>

            {/* ── Bottom-right: Point count ── */}
            <div style={{
                position: "absolute", bottom: 6, right: 8,
                background: "rgba(0,0,0,0.55)", color: "#aaa",
                fontSize: 10, padding: "2px 6px", borderRadius: 3, fontFamily: "monospace",
            }}>
                {info}
            </div>

            {/* ── Bottom-left: Interaction hint ── */}
            <div style={{
                position: "absolute", bottom: 6, left: 8,
                color: "#555", fontSize: 9, fontFamily: "monospace",
            }}>
                LMB: {mode} | RMB: pan | Scroll: zoom
            </div>
        </div>
    );
};

const tbStyle: React.CSSProperties = {
    background: "rgba(0,0,0,0.5)",
    color: "#aaa",
    border: "1px solid #444",
    borderRadius: 3,
    width: 24, height: 24,
    fontSize: 12, fontWeight: 600,
    cursor: "pointer",
    display: "flex", alignItems: "center", justifyContent: "center",
    padding: 0,
};
