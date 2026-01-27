import React, { useRef, useState, useEffect } from "react";
import { DashboardWidget, PublishedPortData, BlueprintNodeData, TypeDescriptor } from "../../types";
import { Node } from "reactflow";

interface DashboardCanvasProps {
    mode: "design" | "view";
    widgets: DashboardWidget[];
    selectedWidgetId: string | null;
    snapToGrid: boolean;
    onSelectWidget: (id: string | null) => void;
    onUpdateWidget: (id: string, updates: Partial<DashboardWidget>) => void;
    onDeleteWidget: (id: string) => void;
    onAddWidget?: (widget: DashboardWidget) => void; // Added prop
    outputs: Record<string, unknown>;
    nodes: Node<BlueprintNodeData>[];
    onInputChange?: (nodeId: string, portName: string, value: any) => void;
}

const GRID_SIZE = 20;

const DashboardCanvas: React.FC<DashboardCanvasProps> = ({
    mode,
    widgets,
    selectedWidgetId,
    snapToGrid,
    onSelectWidget,
    onUpdateWidget,
    onDeleteWidget,
    onAddWidget,
    outputs,
    nodes,
    onInputChange
}) => {
    const canvasRef = useRef<HTMLDivElement>(null);
    const [viewport, setViewport] = useState({ x: 0, y: 0, zoom: 1 });
    const [editingWidgetId, setEditingWidgetId] = useState<string | null>(null);
    const [dragState, setDragState] = useState<{
        isDragging: boolean;
        type: 'widget' | 'pan';
        widgetId: string | null;
        startX: number;
        startY: number;
        initialX: number;
        initialY: number;
        initialW: number;
        initialH: number;
        handle?: string;
    } | null>(null);

    // Helpers
    const snap = (val: number) => snapToGrid ? Math.round(val / GRID_SIZE) * GRID_SIZE : val;

    // --- Inputs ---

    const handleWheel = (e: React.WheelEvent) => {
        // Zoom
        e.stopPropagation(); // Standardize
        const ZOOM_SENSITIVITY = 0.001;
        const minZoom = 0.1;
        const maxZoom = 5;

        const delta = -e.deltaY * ZOOM_SENSITIVITY;
        let newZoom = viewport.zoom + delta;
        newZoom = Math.max(minZoom, Math.min(maxZoom, newZoom));

        // Zoom towards mouse
        // 1. Mouse pos relative to canvas viewport (screen pixels)
        const rect = canvasRef.current!.getBoundingClientRect();
        const mouseX = e.clientX - rect.left;
        const mouseY = e.clientY - rect.top;

        // 2. Mouse pos in world coordinates (before zoom change)
        const worldX = (mouseX - viewport.x) / viewport.zoom;
        const worldY = (mouseY - viewport.y) / viewport.zoom;

        // 3. Calculate new viewport x/y to keep worldX/worldY at same screen pos
        // mouseX = newX + worldX * newZoom
        const newX = mouseX - worldX * newZoom;
        const newY = mouseY - worldY * newZoom;

        setViewport({ x: newX, y: newY, zoom: newZoom });
    };

    const handlePointerDown = (e: React.PointerEvent, widget: DashboardWidget | null = null, handle: string = "move") => {
        if (editingWidgetId) {
            // If clicking outside while editing, stop editing
            if (widget?.id !== editingWidgetId) {
                setEditingWidgetId(null);
            }
            // Allow interaction with input if clicking same widget
            if (widget?.id === editingWidgetId) {
                e.stopPropagation();
                return;
            }
        }

        e.preventDefault(); // Prevent text selection etc
        e.stopPropagation();

        // Right Click or Middle Click -> Pan
        if (e.button === 1 || e.button === 2) {
            e.currentTarget.setPointerCapture(e.pointerId);
            setDragState({
                isDragging: true,
                type: 'pan',
                widgetId: null,
                startX: e.clientX,
                startY: e.clientY,
                initialX: viewport.x,
                initialY: viewport.y,
                initialW: 0, initialH: 0
            });
            return;
        }

        // Left Click -> Widget Interaction
        if (mode === "design" && widget) {
            e.currentTarget.setPointerCapture(e.pointerId);
            onSelectWidget(widget.id);
            setDragState({
                isDragging: true,
                type: 'widget',
                widgetId: widget.id,
                startX: e.clientX,
                startY: e.clientY,
                initialX: widget.x,
                initialY: widget.y,
                initialW: widget.w,
                initialH: widget.h,
                handle
            });
        } else if (mode === "design") {
            // Clicked empty space -> deselect
            onSelectWidget(null);
            setEditingWidgetId(null);
        }
    };

    const handleDoubleClick = (e: React.MouseEvent, widget: DashboardWidget) => {
        if (mode === "design" && widget.type === 'label') {
            e.stopPropagation();
            setEditingWidgetId(widget.id);
        }
    };

    const handlePointerMove = (e: React.PointerEvent) => {
        if (!dragState || !dragState.isDragging) return;

        const rawDx = e.clientX - dragState.startX;
        const rawDy = e.clientY - dragState.startY;

        if (dragState.type === 'pan') {
            setViewport(prev => ({
                ...prev,
                x: dragState.initialX + rawDx,
                y: dragState.initialY + rawDy
            }));
            return;
        }

        if (dragState.type === 'widget' && mode === "design") {
            // Apply zoom scaling to deltas
            const dx = rawDx / viewport.zoom;
            const dy = rawDy / viewport.zoom;

            const updates: Partial<DashboardWidget> = {};

            if (dragState.handle === "move") {
                updates.x = snap(dragState.initialX + dx);
                updates.y = snap(dragState.initialY + dy);
            } else {
                // Resize logic
                const w = dragState.initialW;
                const h = dragState.initialH;
                const x = dragState.initialX;
                const y = dragState.initialY;

                let newW = w;
                let newH = h;
                let newX = x;
                let newY = y;
                const hdl = dragState.handle || "";

                if (hdl.includes("e")) newW = Math.max(GRID_SIZE, w + dx);
                if (hdl.includes("w")) {
                    const delta = Math.min(w - GRID_SIZE, dx);
                    newX = x + delta;
                    newW = w - delta;
                }
                if (hdl.includes("s")) newH = Math.max(GRID_SIZE, h + dy);
                if (hdl.includes("n")) {
                    const delta = Math.min(h - GRID_SIZE, dy);
                    newY = y + delta;
                    newH = h - delta;
                }

                if (snapToGrid) {
                    updates.w = Math.round(newW / GRID_SIZE) * GRID_SIZE;
                    updates.h = Math.round(newH / GRID_SIZE) * GRID_SIZE;
                    updates.x = Math.round(newX / GRID_SIZE) * GRID_SIZE;
                    updates.y = Math.round(newY / GRID_SIZE) * GRID_SIZE;
                } else {
                    updates.w = newW; updates.h = newH;
                    updates.x = newX; updates.y = newY;
                }
            }

            if (dragState.widgetId) {
                onUpdateWidget(dragState.widgetId, updates);
            }
        }
    };

    const handlePointerUp = (e: React.PointerEvent) => {
        if (dragState) {
            e.currentTarget.releasePointerCapture(e.pointerId);
            setDragState(null);
        }
    };

    const handleLabelChange = (id: string, newLabel: string) => {
        onUpdateWidget(id, { label: newLabel });
    };

    const handleLabelBlur = () => {
        setEditingWidgetId(null);
    };

    const handleLabelKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter') {
            setEditingWidgetId(null);
        }
        e.stopPropagation();
    };


    // Render Widget Content
    const renderWidgetContent = (widget: DashboardWidget) => {
        const isEditing = editingWidgetId === widget.id;

        // Find bound node/value if applicable
        let value: any = null;
        if (widget.nodeId && widget.portName) {
            // 1. Try outputs prop
            if (outputs[widget.nodeId] && (outputs[widget.nodeId] as any)[widget.portName] !== undefined) {
                value = (outputs[widget.nodeId] as any)[widget.portName];
            } else {
                // 2. Try node cached last_outputs
                const node = nodes.find(n => n.id === widget.nodeId);
                if (node?.data.last_outputs) {
                    value = node.data.last_outputs[widget.portName];
                }
                // 3. Try node inputs if it's an input widget
                if (node && node.data.inputValues && node.data.inputValues[widget.portName] !== undefined && widget.type === 'bound-input') {
                    value = node.data.inputValues[widget.portName];
                }
            }
        }

        switch (widget.type) {
            case "label":
                if (isEditing) {
                    return (
                        <input
                            autoFocus
                            type="text"
                            value={widget.label || ""}
                            onChange={(e) => handleLabelChange(widget.id, e.target.value)}
                            onBlur={handleLabelBlur}
                            onKeyDown={handleLabelKeyDown}
                            onPointerDown={e => e.stopPropagation()}
                            style={{
                                width: '100%', height: '100%',
                                border: 'none', background: 'transparent',
                                fontSize: 'inherit', fontWeight: 'inherit', color: 'inherit',
                                outline: 'none'
                            }}
                        />
                    );
                }
                return <div style={{ width: '100%', height: '100%', display: 'flex', alignItems: 'center' }}>{widget.label || "Label"}</div>;
            case "container":
                return <div style={{ width: '100%', height: '100%', border: '1px dashed var(--border-subtle)', borderRadius: '4px' }}></div>;
            case "bound-output":
                if (typeof value === "string" && (value.startsWith("data:image") || value.startsWith("http"))) {
                    return <img src={value} alt="output" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />;
                } else if (value && typeof value === 'object' && (value as any)._type === 'StreamResource') {
                    const stream = value as any;
                    return (
                        <div style={{ width: '100%', height: '100%', position: 'relative', background: '#000' }}>
                            <img src={`/api/streams/${stream.stream_id}/frame?ts=${Date.now()}`} alt="stream" style={{ width: '100%', height: '100%', objectFit: 'contain' }} />
                        </div>
                    );
                }
                return (
                    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
                        {widget.label && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{widget.label}</div>}
                        <div style={{ flex: 1, background: 'var(--bg-tertiary)', padding: '8px', borderRadius: '4px', overflow: 'auto', fontFamily: 'monospace', whiteSpace: 'pre-wrap' }}>
                            {value !== undefined ? (typeof value === 'object' ? JSON.stringify(value, null, 2) : String(value)) : <span style={{ opacity: 0.5 }}>No Data</span>}
                        </div>
                    </div>
                );
            case "bound-input":
                return (
                    <div style={{ width: '100%', height: '100%', display: 'flex', flexDirection: 'column' }}>
                        {widget.label && <div style={{ fontSize: '11px', color: 'var(--text-muted)', marginBottom: '4px' }}>{widget.label}</div>}
                        <input
                            type="text"
                            value={value ?? ""}
                            readOnly={mode === "view"}
                            onChange={(e) => onInputChange?.(widget.nodeId!, widget.portName!, e.target.value)}
                            onPointerDown={e => e.stopPropagation()} // Allow interaction without drag
                            style={{
                                width: '100%', padding: '8px', background: 'var(--bg-input)', border: '1px solid var(--border-input)', borderRadius: '4px', color: 'var(--text-primary)'
                            }}
                        />
                    </div>
                );
            default:
                return <div>Unknown Widget</div>;
        }
    };

    return (
        <div
            ref={canvasRef}
            className={`dashboard-canvas ${mode}`}
            style={{
                width: '100%',
                height: '100%',
                overflow: 'hidden', // Infinite canvas hides scrollbars, we Pan
                position: 'relative',
                background: 'var(--bg-canvas)',
                cursor: dragState?.type === 'pan' ? 'grabbing' : 'default',
                userSelect: 'none'
            }}
            onContextMenu={e => e.preventDefault()}
            onPointerDown={e => handlePointerDown(e, null)}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onWheel={handleWheel}

            // Drag and Drop
            onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(e) => {
                e.preventDefault();
                const data = e.dataTransfer.getData("application/reactflow-widget");
                if (data && onAddWidget) {
                    try {
                        const widgetData = JSON.parse(data);

                        // Calculate Drop Position
                        const rect = canvasRef.current!.getBoundingClientRect();
                        const mouseX = e.clientX - rect.left;
                        const mouseY = e.clientY - rect.top;

                        // Convert to World Coordinates
                        const worldX = (mouseX - viewport.x) / viewport.zoom;
                        const worldY = (mouseY - viewport.y) / viewport.zoom;

                        // Snap if needed
                        const x = snapToGrid ? Math.round(worldX / GRID_SIZE) * GRID_SIZE : worldX;
                        const y = snapToGrid ? Math.round(worldY / GRID_SIZE) * GRID_SIZE : worldY;

                        onAddWidget({
                            id: `widget-${Date.now()}`,
                            type: widgetData.type,
                            label: widgetData.label,
                            x: x,
                            y: y,
                            w: widgetData.w,
                            h: widgetData.h,
                            nodeId: widgetData.nodeId,
                            portName: widgetData.portName,
                            style: widgetData.style || {}
                        });
                    } catch (err) {
                        console.error("Failed to parse widget drop data", err);
                    }
                }
            }}
        >
            <div className="transform-layer" style={{
                transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
                transformOrigin: '0 0',
                width: '100%', height: '100%',
                position: 'absolute',
                pointerEvents: 'none' // Events bubble up to parent, widgets enable pointer events
            }}>
                {/* Grid Background */}
                {mode === "design" && snapToGrid && (
                    <div style={{
                        position: 'absolute', left: -50000, top: -50000, width: 100000, height: 100000,
                        backgroundImage: `radial-gradient(circle, #333 1px, transparent 1px)`,
                        backgroundSize: `${GRID_SIZE}px ${GRID_SIZE}px`,
                        opacity: 0.5,
                        pointerEvents: 'none',
                        zIndex: -1
                    }} />
                )}

                {widgets.map(widget => {
                    const isSelected = selectedWidgetId === widget.id;
                    const isRoot = widget.id === "root-container";
                    let isComputing = false;
                    if (widget.nodeId) {
                        const node = nodes.find(n => n.id === widget.nodeId);
                        if (node?.data.executionStatus === "running") isComputing = true;
                    }

                    // Apply styles
                    const customStyle: React.CSSProperties = widget.style ? (widget.style as React.CSSProperties) : {};
                    // Ensure border style is solid if width is present but style is absent
                    if (customStyle.borderWidth && !customStyle.borderStyle) {
                        customStyle.borderStyle = 'solid';
                    }

                    const zIndex = isRoot ? 0 : (isSelected ? 100 : (widget.zIndex ?? 1));

                    return (
                        <div
                            key={widget.id}
                            className="dashboard-widget-wrapper"
                            style={{
                                position: 'absolute',
                                left: widget.x,
                                top: widget.y,
                                width: widget.w,
                                height: widget.h,
                                boxSizing: 'border-box',
                                // Use outline for selection so we don't override custom borders
                                outline: mode === "design" && isSelected && !isRoot ? '2px solid var(--accent-primary)' : 'none',
                                // border: mode === "design" && isSelected && !isRoot ? '1px solid var(--accent-primary)' : '1px solid transparent', // REMOVED
                                background: isRoot ? 'transparent' : 'var(--bg-surface)',
                                borderRadius: '4px',
                                boxShadow: isRoot ? 'none' : '0 2px 4px rgba(0,0,0,0.2)',

                                ...customStyle, // Overrides (background, border, etc). User must be careful not to break layout

                                zIndex: zIndex,
                                pointerEvents: 'auto'
                            }}
                            onPointerDown={(e) => !isRoot && handlePointerDown(e, widget)}
                            onDoubleClick={(e) => handleDoubleClick(e, widget)}
                        >
                            <div style={{ width: '100%', height: '100%', overflow: 'hidden', padding: isRoot ? 0 : '8px', position: 'relative' }}>
                                {renderWidgetContent(widget)}
                                {isComputing && (
                                    <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(1px)', zIndex: 5 }}>
                                        <div className="btn-spinner" style={{ width: '20px', height: '20px', borderWidth: '2px' }}></div>
                                    </div>
                                )}
                            </div>

                            {/* Resize Handle (Bottom Right) - Show for all widgets, visible when selected or on hover */}
                            {mode === "design" && !isRoot && (
                                <div
                                    className={`hover-resize-handle ${isSelected ? 'selected' : ''}`}
                                    style={{
                                        position: 'absolute',
                                        bottom: 0,
                                        right: 0,
                                        width: 16,
                                        height: 16,
                                        cursor: 'se-resize',
                                        zIndex: isSelected ? 1000 : 50,
                                        display: 'flex',
                                        alignItems: 'end',
                                        justifyContent: 'end',
                                        padding: '2px',
                                        opacity: isSelected ? 1 : 0, // Visible when selected, hidden when not selected (shown on hover via CSS)
                                        transition: 'opacity 0.2s'
                                    }}
                                    onPointerDown={(e) => handlePointerDown(e, widget, 'se')}
                                >
                                    {/* Icon */}
                                    <svg width="10" height="10" viewBox="0 0 10 10" fill="var(--text-muted)">
                                        <path d="M10 10 L10 2 L2 10 Z" />
                                    </svg>
                                </div>
                            )}

                            {/* Selected-only UI elements */}
                            {mode === "design" && isSelected && !isRoot && (
                                <>

                                    <div
                                        className="delete-handle"
                                        style={{
                                            position: 'absolute',
                                            top: -12,
                                            right: -12,
                                            width: 24,
                                            height: 24,
                                            background: 'var(--status-error)',
                                            color: 'white',
                                            borderRadius: '50%',
                                            cursor: 'pointer',
                                            display: 'flex',
                                            alignItems: 'center',
                                            justifyContent: 'center',
                                            boxShadow: '0 2px 5px rgba(0,0,0,0.3)',
                                            zIndex: 20
                                        }}
                                        onPointerDown={(e) => { e.stopPropagation(); onDeleteWidget(widget.id); }}
                                        title="Remove Widget"
                                    >
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                            <line x1="18" y1="6" x2="6" y2="18"></line>
                                            <line x1="6" y1="6" x2="18" y2="18"></line>
                                        </svg>
                                    </div>
                                </>
                            )}
                        </div>
                    );
                })}
            </div>
        </div>
    );
};

export default DashboardCanvas;
