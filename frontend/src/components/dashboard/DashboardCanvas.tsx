import React, { useRef, useState, useEffect } from "react";
import { DashboardWidget, DashboardLayout, BlueprintNodeData } from "../../types";
import { Node } from "reactflow";
import { DashboardWidgetContent } from "./DashboardWidgetContent";

interface DashboardCanvasProps {
    mode: "design" | "view";
    widgets: DashboardWidget[];
    selectedWidgetId: string | null;
    snapToGrid: boolean;
    onSelectWidget: (id: string | null) => void;
    onUpdateWidget: (id: string, updates: Partial<DashboardWidget>) => void;
    onDeleteWidget: (id: string) => void;
    onAddWidget?: (widget: DashboardWidget) => void;
    outputs: Record<string, unknown>;
    nodes: Node<BlueprintNodeData>[];
    onInputChange?: (nodeId: string, portName: string, value: any) => void;
    viewBounds?: { x: number; y: number; w: number; h: number };
    onUpdateViewBounds?: (bounds: { x: number; y: number; w: number; h: number }) => void;
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
    onInputChange,
    viewBounds,
    onUpdateViewBounds
}) => {
    const canvasRef = useRef<HTMLDivElement>(null);
    const [viewport, setViewport] = useState({ x: 0, y: 0, zoom: 1 });
    const [editingWidgetId, setEditingWidgetId] = useState<string | null>(null);
    const [hoveredWidgetId, setHoveredWidgetId] = useState<string | null>(null);
    const [dragState, setDragState] = useState<{
        isDragging: boolean;
        type: 'widget' | 'pan' | 'viewBounds';
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

    // -- View Mode Specific Logic --
    const [containerSize, setContainerSize] = useState({ width: 0, height: 0 });

    useEffect(() => {
        if (!canvasRef.current) return;

        const updateSize = () => {
            if (canvasRef.current) {
                setContainerSize({
                    width: canvasRef.current.clientWidth,
                    height: canvasRef.current.clientHeight
                });
            }
        };

        updateSize();
        const observer = new ResizeObserver(updateSize);
        observer.observe(canvasRef.current);

        return () => observer.disconnect();
    }, []);

    // Derived values for View Mode
    const viewModeMetrics = React.useMemo(() => {
        if (mode === "design" || !viewBounds || containerSize.width === 0 || containerSize.height === 0)
            return { scale: 1, width: 0, height: 0, minX: 0, minY: 0, initialScrollX: 0, initialScrollY: 0 };

        // 1. Calculate Scale to FIT ViewBounds into Container (Width AND Height)
        const scaleX = containerSize.width / viewBounds.w;
        const scaleY = containerSize.height / viewBounds.h;
        const scale = Math.min(scaleX, scaleY);

        // 2. Calculate Content Bounds (Union of ViewBounds and All Widgets)
        let minX = viewBounds.x;
        let minY = viewBounds.y;
        let maxX = viewBounds.x + viewBounds.w;
        let maxY = viewBounds.y + viewBounds.h;

        widgets.forEach(w => {
            minX = Math.min(minX, w.x);
            minY = Math.min(minY, w.y);
            maxX = Math.max(maxX, w.x + w.w);
            maxY = Math.max(maxY, w.y + w.h);
        });

        // 3. Calculate Scaled Content Size
        const width = (maxX - minX) * scale;
        const height = (maxY - minY) * scale;

        return {
            scale,
            width,
            height,
            minX,
            minY,
            initialScrollX: (viewBounds.x - minX) * scale,
            initialScrollY: (viewBounds.y - minY) * scale
        };
    }, [mode, widgets, viewBounds, containerSize.width, containerSize.height]);

    // Set initial scroll position when entering View Mode
    useEffect(() => {
        if (mode === "view" && canvasRef.current && viewBounds) {
            requestAnimationFrame(() => {
                if (canvasRef.current) {
                    canvasRef.current.scrollLeft = viewModeMetrics.initialScrollX;
                    canvasRef.current.scrollTop = viewModeMetrics.initialScrollY;
                }
            });
        }
    }, [mode, viewModeMetrics.initialScrollX, viewModeMetrics.initialScrollY]);


    const handleWheel = (e: React.WheelEvent) => {
        if (mode === "view") return; // Allow native scrolling in view mode

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
        if (mode === "view") return;

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



        // Right Click (2) or Middle Click (1) -> Pan
        if (e.button !== 0) {
            // Capture on canvas, not the widget, for smooth panning
            canvasRef.current?.setPointerCapture(e.pointerId);
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

        // Left Click (0) -> Widget Interaction
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

        if (mode === "design" && dragState.type === 'widget') {
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

        if (mode === "design" && dragState.type === 'viewBounds' && onUpdateViewBounds) {
            const dx = rawDx / viewport.zoom;
            const dy = rawDy / viewport.zoom;

            let newBounds = {
                x: dragState.initialX,
                y: dragState.initialY,
                w: dragState.initialW,
                h: dragState.initialH
            };

            if (dragState.handle === "move") {
                newBounds.x = snap(dragState.initialX + dx);
                newBounds.y = snap(dragState.initialY + dy);
            } else {
                // Resize logic (se only for now)
                const w = dragState.initialW;
                const h = dragState.initialH;

                if (dragState.handle === 'se') {
                    const newW = Math.max(GRID_SIZE * 10, w + dx);
                    const newH = Math.max(GRID_SIZE * 10, h + dy);

                    if (snapToGrid) {
                        newBounds.w = Math.round(newW / GRID_SIZE) * GRID_SIZE;
                        newBounds.h = Math.round(newH / GRID_SIZE) * GRID_SIZE;
                    } else {
                        newBounds.w = newW;
                        newBounds.h = newH;
                    }
                }
            }
            onUpdateViewBounds(newBounds);
        }
    };

    const handlePointerUp = (e: React.PointerEvent) => {
        if (dragState) {
            e.currentTarget.releasePointerCapture(e.pointerId);
            setDragState(null);
        }
    };

    // Local handlers for focus mgmt only
    // Moved complex render logic to DashboardWidgetContent

    // Better implementation of useEffect above with dependencies
    useEffect(() => {
        // Design mode auto-fit or initial load logic...
        // For View Mode, we use the derived `viewModeScale` and don't touch `viewport`.
        // We'll keep this strictly for "Fit View" button if we had one, or initial setup.
    }, [mode]);

    return (
        <div
            ref={canvasRef}
            className={`dashboard-canvas ${mode}`}
            style={{
                width: '100%',
                height: '100%',
                overflow: mode === "view" ? "auto" : "hidden", // Enable scroll in view mode
                position: 'relative',
                background: 'var(--bg-canvas)',
                cursor: mode === "design" && dragState?.type === 'pan' ? 'grabbing' : 'default',
                userSelect: 'none'
            }}
            onContextMenu={e => mode === "design" ? e.preventDefault() : undefined}
            onPointerDown={e => handlePointerDown(e, null)}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onWheel={handleWheel}

            // Drag and Drop (Design only essentially)
            onDragOver={(e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = "copy";
            }}
            onDrop={(e) => {
                e.preventDefault();
                // ... (Keep existing drop logic, maybe guard with mode==="design" inside)
                if (mode === "view") return;
                const data = e.dataTransfer.getData("application/reactflow-widget");
                if (data && onAddWidget) {
                    try {
                        const widgetData = JSON.parse(data);

                        // Calculate Drop Position
                        const rect = canvasRef.current!.getBoundingClientRect();
                        const mouseX = e.clientX - rect.left;
                        const mouseY = e.clientY - rect.top;

                        // To World - Design Mode uses viewport
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
            {mode === "view" ? (
                // VIEW MODE RENDER
                <div
                    className="view-mode-content-wrapper"
                    style={{
                        width: viewModeMetrics.width,
                        height: viewModeMetrics.height,
                        position: 'relative',
                    }}
                >
                    <div className="transform-layer" style={{
                        transform: `scale(${viewModeMetrics.scale}) translate(${-viewModeMetrics.minX}px, ${-viewModeMetrics.minY}px)`,
                        transformOrigin: '0 0',
                        width: '100%', height: '100%',
                        position: 'absolute',
                        pointerEvents: 'none'
                    }}>
                        {/* Render Widgets in View Mode */}
                        {widgets.map(widget => {
                            const isComputing = widget.nodeId && nodes.find(n => n.id === widget.nodeId)?.data.executionStatus === "running";
                            const customStyle: React.CSSProperties = widget.style ? (widget.style as React.CSSProperties) : {};
                            if (customStyle.borderWidth && !customStyle.borderStyle) customStyle.borderStyle = 'solid';

                            return (
                                <div
                                    key={widget.id}
                                    style={{
                                        position: 'absolute',
                                        left: widget.x,
                                        top: widget.y,
                                        width: widget.w,
                                        height: widget.h,
                                        boxSizing: 'border-box',
                                        background: 'transparent',
                                        borderRadius: '4px',
                                        boxShadow: 'none',
                                        ...customStyle,
                                        zIndex: widget.id === "root-container" ? 0 : (widget.zIndex ?? 1),
                                        pointerEvents: 'auto'
                                    }}
                                >
                                    <div style={{ width: '100%', height: '100%', overflow: 'hidden', padding: widget.id === "root-container" ? 0 : '8px', position: 'relative' }}>
                                        <DashboardWidgetContent
                                            widget={widget}
                                            mode={mode}
                                            nodes={nodes}
                                            outputs={outputs}
                                            editingWidgetId={editingWidgetId}
                                            setEditingWidgetId={setEditingWidgetId}
                                            onUpdateWidget={onUpdateWidget}
                                            onInputChange={onInputChange}
                                        />
                                        {isComputing && (
                                            <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(1px)', zIndex: 5 }}>
                                                <div className="btn-spinner" style={{ width: '20px', height: '20px', borderWidth: '2px' }}></div>
                                            </div>
                                        )}
                                    </div>
                                </div>
                            );
                        })}
                    </div>
                </div>
            ) : (
                // DESIGN MODE RENDER (Original)
                <div className="transform-layer" style={{
                    transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
                    transformOrigin: '0 0',
                    width: '100%', height: '100%',
                    position: 'absolute',
                    pointerEvents: 'none'
                }}>
                    {/* Grid Background */}
                    {snapToGrid && (
                        <div style={{
                            position: 'absolute', left: -50000, top: -50000, width: 100000, height: 100000,
                            backgroundImage: `radial-gradient(circle, #333 1px, transparent 1px)`,
                            backgroundSize: `${GRID_SIZE}px ${GRID_SIZE}px`,
                            opacity: 0.5,
                            pointerEvents: 'none',
                            zIndex: -1
                        }} />
                    )}

                    {/* View Bounds Rectangle (Design Mode Only) */}
                    {viewBounds && (
                        <div
                            className="view-bounds-rect"
                            style={{
                                position: 'absolute',
                                left: viewBounds.x,
                                top: viewBounds.y,
                                width: viewBounds.w,
                                height: viewBounds.h,
                                border: '2px dashed #666',
                                pointerEvents: 'auto',
                                zIndex: 0
                            }}
                            onPointerDown={(e) => {
                                if (e.button !== 0) return;
                                // Deselect widgets when interacting with view bounds
                                onSelectWidget(null);
                                setEditingWidgetId(null);
                                e.currentTarget.setPointerCapture(e.pointerId);
                                setDragState({
                                    isDragging: true,
                                    type: 'viewBounds',
                                    widgetId: null,
                                    startX: e.clientX,
                                    startY: e.clientY,
                                    initialX: viewBounds.x,
                                    initialY: viewBounds.y,
                                    initialW: viewBounds.w,
                                    initialH: viewBounds.h,
                                    handle: 'move'
                                });
                                e.stopPropagation();
                            }}
                        >
                            <div style={{ position: 'absolute', top: -20, left: 0, fontSize: '12px', color: '#888', whiteSpace: 'nowrap' }}>
                                View Area ({viewBounds.w} x {viewBounds.h})
                            </div>
                            <div
                                style={{
                                    position: 'absolute',
                                    bottom: -5, right: -5,
                                    width: 10, height: 10,
                                    background: '#666',
                                    cursor: 'se-resize',
                                    pointerEvents: 'auto'
                                }}
                                onPointerDown={(e) => {
                                    if (e.button !== 0) return;
                                    e.currentTarget.setPointerCapture(e.pointerId);
                                    setDragState({
                                        isDragging: true,
                                        type: 'viewBounds',
                                        widgetId: null,
                                        startX: e.clientX,
                                        startY: e.clientY,
                                        initialX: viewBounds.x,
                                        initialY: viewBounds.y,
                                        initialW: viewBounds.w,
                                        initialH: viewBounds.h,
                                        handle: 'se'
                                    });
                                    e.stopPropagation();
                                }}
                            />
                        </div>
                    )}

                    {widgets.map(widget => {
                        // Design Mode Widget Render (includes handles, selection, etc)
                        const isSelected = selectedWidgetId === widget.id;
                        const isRoot = widget.id === "root-container";
                        let isComputing = false;
                        if (widget.nodeId) {
                            const node = nodes.find(n => n.id === widget.nodeId);
                            if (node?.data.executionStatus === "running") isComputing = true;
                        }

                        const customStyle: React.CSSProperties = widget.style ? (widget.style as React.CSSProperties) : {};
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
                                    outline: 'none',
                                    background: 'transparent',
                                    borderRadius: '4px',
                                    boxShadow: isSelected && !isRoot
                                        ? '0 0 0 2px var(--selection-yellow), 0 4px 16px rgba(0, 0, 0, 0.4)'
                                        : (hoveredWidgetId === widget.id && !isRoot ? '0 0 0 1px var(--selection-yellow-light), 0 4px 12px rgba(0, 0, 0, 0.3)' : 'none'),
                                    ...customStyle,
                                    zIndex: zIndex,
                                    pointerEvents: 'auto'
                                }}
                                onPointerDown={(e) => !isRoot && handlePointerDown(e, widget)}
                                onPointerEnter={() => !isRoot && setHoveredWidgetId(widget.id)}
                                onPointerLeave={() => !isRoot && setHoveredWidgetId(null)}
                                onDoubleClick={(e) => handleDoubleClick(e, widget)}
                            >
                                <div style={{ width: '100%', height: '100%', overflow: 'hidden', padding: isRoot ? 0 : '8px', position: 'relative' }}>
                                    <DashboardWidgetContent
                                        widget={widget}
                                        mode={mode}
                                        nodes={nodes}
                                        outputs={outputs}
                                        editingWidgetId={editingWidgetId}
                                        setEditingWidgetId={setEditingWidgetId}
                                        onUpdateWidget={onUpdateWidget}
                                        onInputChange={onInputChange}
                                    />
                                    {isComputing && (
                                        <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center', backdropFilter: 'blur(1px)', zIndex: 5 }}>
                                            <div className="btn-spinner" style={{ width: '20px', height: '20px', borderWidth: '2px' }}></div>
                                        </div>
                                    )}
                                </div>

                                {/* Resize Handle (Bottom Right) */}
                                {!isRoot && (
                                    <div
                                        className={`hover-resize-handle ${isSelected ? 'selected' : ''}`}
                                        style={{
                                            position: 'absolute', bottom: 0, right: 0, width: 16, height: 16, cursor: 'se-resize', zIndex: isSelected ? 1000 : 50,
                                            display: 'flex', alignItems: 'end', justifyContent: 'end', padding: '2px',
                                            opacity: isSelected ? 1 : 0, transition: 'opacity 0.2s'
                                        }}
                                        onPointerDown={(e) => {
                                            if (e.button !== 0) return;
                                            handlePointerDown(e, widget, 'se');
                                        }}
                                    >
                                        <svg width="10" height="10" viewBox="0 0 10 10" fill="var(--text-muted)">
                                            <path d="M10 10 L10 2 L2 10 Z" />
                                        </svg>
                                    </div>
                                )}

                                {/* Delete Handle */}
                                {isSelected && !isRoot && (
                                    <div
                                        className="delete-handle"
                                        style={{
                                            position: 'absolute', top: -12, right: -12, width: 24, height: 24, background: 'var(--status-error)',
                                            color: 'white', borderRadius: '50%', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center',
                                            boxShadow: '0 2px 5px rgba(0,0,0,0.3)', zIndex: 20
                                        }}
                                        onPointerDown={(e) => {
                                            if (e.button !== 0) return;
                                            e.stopPropagation();
                                            onDeleteWidget(widget.id);
                                        }}
                                        title="Remove Widget"
                                    >
                                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                                            <line x1="18" y1="6" x2="6" y2="18"></line>
                                            <line x1="6" y1="6" x2="18" y2="18"></line>
                                        </svg>
                                    </div>
                                )}
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
};

export default DashboardCanvas;
