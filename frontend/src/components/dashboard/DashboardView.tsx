import React, { useState, useMemo, useEffect, useRef, useCallback } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, DashboardLayout, DashboardWidget, PublishedPortData } from "../../types";
import DashboardCanvas from "./DashboardCanvas";
import DashboardPalette from "./DashboardPalette";
import DashboardProperties from "./DashboardProperties";
import DashboardViewportProperties from "./DashboardViewportProperties";

interface DashboardViewProps {
    nodes: Node<BlueprintNodeData>[];
    outputs: Record<string, unknown>;
    onRunGraph?: () => void;
    isRunning?: boolean;
    onInputChange?: (nodeId: string, portName: string, value: any) => void;
    onSave?: () => void;
    publishedItems?: { nodeId: string; nodeName: string; port: PublishedPortData }[];
    onJumpToNode?: (nodeId: string) => void;
    onTogglePublish?: (nodeId: string, portId: string, direction: "input" | "output", kind: any) => void;
    onDirtyChange?: (isDirty: boolean) => void;
    layout: DashboardLayout;
    onLayoutChange: (layout: DashboardLayout) => void;
}

const DashboardView: React.FC<DashboardViewProps> = ({ nodes, outputs, onRunGraph, isRunning, onInputChange, onSave, publishedItems = [], onJumpToNode, onTogglePublish, onDirtyChange, layout, onLayoutChange }) => {
    const [mode, setMode] = useState<"design" | "view">("design");
    // Layout state lifted to parent
    const [selectedWidgetId, setSelectedWidgetId] = useState<string | null>(null);
    const [snapToGrid, setSnapToGrid] = useState(true);

    // Panel states
    const [leftPanelWidth, setLeftPanelWidth] = useState(260);
    const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
    const [rightPanelWidth, setRightPanelWidth] = useState(300);
    const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);

    // Panel resizing refs
    const isResizingLeft = useRef(false);
    const isResizingRight = useRef(false);

    // Panel Resizing Handlers
    const startResizingLeft = useCallback(() => { isResizingLeft.current = true; }, []);
    const startResizingRight = useCallback(() => { isResizingRight.current = true; }, []);
    const stopResizing = useCallback(() => { isResizingLeft.current = false; isResizingRight.current = false; }, []);

    const onMouseMove = useCallback((e: React.MouseEvent) => {
        if (isResizingLeft.current) {
            setLeftPanelWidth(prev => Math.max(200, Math.min(600, e.clientX)));
        }
        if (isResizingRight.current) {
            setRightPanelWidth(prev => Math.max(200, Math.min(600, window.innerWidth - e.clientX)));
        }
    }, []);

    // State History for Undo/Redo
    const [history, setHistory] = useState<{ past: DashboardLayout[]; future: DashboardLayout[] }>({ past: [], future: [] });
    const [isDirty, setIsDirty] = useState(false);

    // Load layout (simulated)
    useEffect(() => {
        // No default root container - infinite canvas
        // In a real app, we would load from backend here and set isDirty to false
        setIsDirty(false);
        onDirtyChange?.(false);
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []); // Intentionally only run on mount

    const pushToHistory = (newLayout: DashboardLayout) => {
        setHistory(prev => ({
            past: [...prev.past, layout],
            future: []
        }));
        onLayoutChange(newLayout);
        setIsDirty(true);
        onDirtyChange?.(true);
    };

    const handleUndo = useCallback(() => {
        setHistory(prev => {
            if (prev.past.length === 0) return prev;
            const previous = prev.past[prev.past.length - 1];
            const newPast = prev.past.slice(0, -1);
            onLayoutChange(previous);
            setIsDirty(true);
            onDirtyChange?.(true);
            return {
                past: newPast,
                future: [layout, ...prev.future]
            };
        });
    }, [layout, onLayoutChange, onDirtyChange]);

    const handleRedo = useCallback(() => {
        setHistory(prev => {
            if (prev.future.length === 0) return prev;
            const next = prev.future[0];
            const newFuture = prev.future.slice(1);
            onLayoutChange(next);
            setIsDirty(true);
            onDirtyChange?.(true);
            return {
                past: [...prev.past, layout],
                future: newFuture
            };
        });
    }, [layout, onLayoutChange, onDirtyChange]);

    // Keyboard Shortcuts for Undo/Redo
    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            // Don't trigger shortcuts when typing in inputs
            const target = e.target as HTMLElement;
            if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable) {
                return;
            }
            if ((e.ctrlKey || e.metaKey) && !e.shiftKey && e.key === 'z') {
                e.preventDefault();
                handleUndo();
            } else if ((e.ctrlKey || e.metaKey) && (e.key === 'y' || (e.shiftKey && e.key === 'z'))) {
                e.preventDefault();
                handleRedo();
            }
        };
        window.addEventListener('keydown', handleKeyDown);
        return () => window.removeEventListener('keydown', handleKeyDown);
    }, [handleUndo, handleRedo]);

    const handleAddWidget = (widget: DashboardWidget) => {
        const newLayout = { ...layout, widgets: [...layout.widgets, widget] };
        pushToHistory(newLayout);
        setSelectedWidgetId(widget.id);
    };

    const handleAddWidgets = (newWidgets: DashboardWidget[]) => {
        const newLayout = { ...layout, widgets: [...layout.widgets, ...newWidgets] };
        pushToHistory(newLayout);
        if (newWidgets.length > 0) {
            setSelectedWidgetId(newWidgets[newWidgets.length - 1].id);
        }
    };

    const handleUpdateWidget = (id: string, updates: Partial<DashboardWidget>) => {
        // We only want to push to history on "committed" changes (like drag end), 
        // but for simplicity we might push on every update. 
        // Optimization: DashboardCanvas should probably only call onUpdateWidget on drag end for history purposes, 
        // or we need a separate "onCommit" prop.
        // For now, let's treat every update as history-worthy (might be spammy for live dragging).
        // A better approach is usually: onDragStart -> save snapshot. onDrag -> update local state. onDragEnd -> commit.
        // However, DashboardCanvas calls onUpdateWidget during drag.

        // TODO: Refactor DashboardCanvas to separate live updates from commit updates?
        // Or check if updates only happen on drag end? 
        // Looking at DashboardCanvas: onUpdateWidget IS called during drag.
        // We should wrap this to debounce or only push history on distinct actions.
        // For this task, getting it working is priority. Let's rely on the user dragging "end" to trigger a separate event if possible? 
        // DashboardCanvas doesn't have an onDragEnd prop for updates.
        // Let's modify handleUpdateWidget to accept a "commit" flag? Or just implement it as is and optimize later.

        // Actually, if we push history on every pixel move, undo will be unusable.
        // We need to know when the operation started/ended.

        // Let's check DashboardCanvas again... it calls onUpdateWidget on pointer move.
        // Changing DashboardCanvas signature is part of the plan anyway for DnD.

        // For now, I will modify this to just update layout directly, 
        // and add a new prop to DashboardCanvas: onWidgetChangeComplete

        onLayoutChange({
            ...layout,
            widgets: layout.widgets.map(w => w.id === id ? { ...w, ...updates } : w)
        });
        setIsDirty(true);
        onDirtyChange?.(true);
    };

    // New handler for commits (start of drag, end of drag, etc) could be added to Canvas.
    // But since I'm editing View first, let's defer precise history triggers.
    // Wait... if I simply don't pushToHistory in handleUpdateWidget, how do we track history for moves?
    // I need a way to snapshot BEFORE a drag starts.

    // Let's implement a 'saveSnapshot' function and pass it down?
    // Or simpler: The Canvas should call a "onInteractionStart" and "onInteractionEnd".

    // Let's add `onInteractionStart` and `onInteractionEnd` to DashboardCanvas props later.
    // For now, I will add a `saveHistorySnapshot` function that I can pass down or call.


    const handleCommitWidgetUpdate = (id: string, updates: Partial<DashboardWidget>) => {
        // This is what we call when we want to save a history point (e.g. mouse up)
        // But we need the *previous* state to be in history? 
        // No, `pushToHistory` saves current `layout` as "past", then sets new layout.
        // So if we call pushToHistory BEFORE applying the final update?

        // Actually, if we've been updating `layout` continuously during drag (without history),
        // then `layout` IS the "future" state already. The "past" state was lost if we didn't save it before drag started.

        // Fix: `pushToHistory` assumes we are transitioning from State A to State B.
        // If we transition A -> A1 -> A2 -> A3 (drag) -> B (drop), we need to save A before A1.

        // Strategy:
        // 1. DashboardCanvas calls `onInteractionStart` -> View saves current layout to a "temp snapshot".
        // 2. DashboardCanvas calls `onUpdateWidget` -> View updates layout (no history).
        // 3. DashboardCanvas calls `onInteractionEnd` -> View pushes "temp snapshot" to history.

        // I will implement this structure.
    };

    const [tempSnapshot, setTempSnapshot] = useState<DashboardLayout | null>(null);

    const onInteractionStart = () => {
        setTempSnapshot(layout);
    };

    const onInteractionEnd = () => {
        if (tempSnapshot) {
            setHistory(prev => ({
                past: [...prev.past, tempSnapshot],
                future: []
            }));
            setTempSnapshot(null); // Clear
            setIsDirty(true);
            onDirtyChange?.(true);
        }
    };

    const handleDeleteWidget = (id: string) => {
        if (id === "root-container") return;
        const newLayout = {
            ...layout,
            widgets: layout.widgets.filter(w => w.id !== id)
        };
        pushToHistory(newLayout);
        if (selectedWidgetId === id) setSelectedWidgetId(null);
    };

    const handleUpdateViewBounds = (bounds: { x: number; y: number; w: number; h: number; style?: Record<string, unknown> }) => {
        // Optimization: Debounce this or separate commit as with widgets if needed
        onLayoutChange({
            ...layout,
            viewport: bounds
        });
        setIsDirty(true);
        onDirtyChange?.(true);
    };

    const selectedWidget = layout.widgets.find(w => w.id === selectedWidgetId) || null;
    const currentViewport = layout.viewport || { x: 0, y: 0, w: 800, h: 600, style: {} };

    // Auto-switch to view mode when running
    useEffect(() => {
        if (isRunning) {
            setMode("view");
            setSelectedWidgetId(null);
        }
    }, [isRunning]);

    const rootRef = useRef<HTMLDivElement>(null);
    const handleFitToScreen = () => {
        if (rootRef.current) {
            const { clientWidth, clientHeight } = rootRef.current;
            handleUpdateViewBounds({
                ...currentViewport,
                x: 0,
                y: 0,
                w: clientWidth,
                h: clientHeight
            });
        }
    };

    return (
        <div
            ref={rootRef}
            className="dashboard-view"
            style={{ display: 'flex', height: '100%', width: '100%', overflow: 'hidden', position: 'relative' }}
            onMouseMove={onMouseMove}
            onMouseUp={stopResizing}
            onMouseLeave={stopResizing}
        >
            {/* Left Panel - Design Mode Only */}
            {mode === "design" && (
                <>
                    <aside
                        className={`side-panel left-panel ${leftPanelCollapsed ? "collapsed" : ""}`}
                        style={{ width: leftPanelCollapsed ? 0 : leftPanelWidth, height: '100%', top: 0, position: 'relative', background: 'var(--bg-surface)' }}
                    >
                        {!leftPanelCollapsed && (
                            <>
                                <DashboardPalette
                                    publishedItems={publishedItems}
                                    onAddWidget={handleAddWidget}
                                    onJumpToNode={onJumpToNode}
                                    onUnpublish={onTogglePublish ? (nodeId: string, portId: string, direction: "input" | "output") => {
                                        // Find the port kind from the node
                                        const node = nodes.find(n => n.id === nodeId);
                                        if (node) {
                                            const portType = direction === "input"
                                                ? node.data.input_port_types?.[portId]
                                                : node.data.output_port_types?.[portId];
                                            onTogglePublish(nodeId, portId, direction, portType);
                                        }
                                    } : undefined}
                                />
                                <div
                                    className="resize-handle right"
                                    onMouseDown={startResizingLeft}
                                />
                            </>
                        )}
                    </aside>

                    <button
                        className="panel-collapse-btn left"
                        style={{ left: leftPanelCollapsed ? 0 : leftPanelWidth, position: 'absolute', top: '50%', zIndex: 100 }}
                        onClick={() => setLeftPanelCollapsed(!leftPanelCollapsed)}
                        title={leftPanelCollapsed ? "Expand Widgets" : "Collapse Widgets"}
                    >
                        {leftPanelCollapsed ? <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" /></svg> : <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z" /></svg>}
                    </button>
                </>
            )}

            {/* Main Canvas Area */}
            <div className="dashboard-main" style={{ flex: 1, position: 'relative', display: 'flex', flexDirection: 'column', minWidth: 0 }}>

                {/* Mode Toggle - Bottom Right */}
                <button
                    onClick={() => {
                        if (mode === "design") { setMode("view"); setSelectedWidgetId(null); }
                        else { setMode("design"); }
                    }}
                    title={mode === "design" ? "Switch to View mode" : "Switch to Design mode"}
                    style={{
                        position: 'absolute',
                        bottom: 16,
                        right: 16,
                        zIndex: 50,
                        width: '36px',
                        height: '36px',
                        borderRadius: '8px',
                        border: '1px solid var(--border-subtle)',
                        background: mode === "view" ? 'var(--bg-elevated)' : 'var(--accent-primary)',
                        color: mode === "view" ? 'var(--text-secondary)' : 'white',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        cursor: 'pointer',
                        boxShadow: '0 2px 8px rgba(0,0,0,0.3)',
                        transition: 'all 0.2s ease',
                        opacity: mode === "view" ? 0.6 : 1,
                    }}
                    onMouseEnter={e => { if (mode === "view") (e.currentTarget as HTMLElement).style.opacity = "1"; }}
                    onMouseLeave={e => { if (mode === "view") (e.currentTarget as HTMLElement).style.opacity = "0.6"; }}
                >
                    {mode === "design" ? (
                        /* Pencil icon - currently in design mode */
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M12 20h9" /><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                        </svg>
                    ) : (
                        /* Eye icon - currently in view mode */
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
                        </svg>
                    )}
                </button>

                {/* Snap to Grid Icon & Undo/Redo - Design Mode Only */}
                {mode === "design" && (
                    <div style={{ position: 'absolute', top: 20, right: 20, zIndex: 50, display: 'flex', gap: '10px' }}>
                        {/* Undo/Redo */}
                        <div style={{
                            background: 'var(--bg-elevated)',
                            padding: '4px',
                            borderRadius: '8px',
                            display: 'flex',
                            gap: '4px',
                            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                            border: '1px solid var(--border-subtle)',
                            alignItems: 'center',
                            height: '36px', // Match Snap Button Height
                            boxSizing: 'border-box'
                        }}>
                            <button
                                onClick={handleUndo}
                                disabled={history.past.length === 0}
                                title="Undo (Ctrl+Z)"
                                className="icon-btn"
                                style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: history.past.length === 0 ? 0.3 : 1 }}>
                                    <path d="M3 7v6h6"></path>
                                    <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"></path>
                                </svg>
                            </button>
                            <button
                                onClick={handleRedo}
                                disabled={history.future.length === 0}
                                title="Redo (Ctrl+Y)"
                                className="icon-btn"
                                style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
                            >
                                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: history.future.length === 0 ? 0.3 : 1 }}>
                                    <path d="M21 7v6h-6"></path>
                                    <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13"></path>
                                </svg>
                            </button>
                        </div>

                        {/* Snap Button */}
                        <button
                            onClick={() => setSnapToGrid(!snapToGrid)}
                            title={`Snap to Grid: ${snapToGrid ? "On" : "Off"}`}
                            style={{
                                width: '36px',
                                height: '36px',
                                borderRadius: '8px',
                                border: '1px solid var(--border-subtle)',
                                background: snapToGrid ? 'var(--accent-primary)' : 'var(--bg-elevated)',
                                color: snapToGrid ? 'white' : 'var(--text-secondary)',
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                cursor: 'pointer',
                                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                                transition: 'all 0.2s ease'
                            }}
                        >
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                                <path d="M10 10h4v4h-4zm0-6h4v4h-4zm0 12h4v4h-4zM4 4h4v4H4zm0 6h4v4H4zm0 6h4v4H4zM16 4h4v4h-4zm0 6h4v4h-4zm0 6h4v4h-4z" />
                            </svg>
                        </button>
                    </div>
                )}

                {/* Canvas */}
                <div className="canvas-wrapper" style={{ flex: 1, position: 'relative', overflow: 'auto', background: 'var(--bg-canvas)' }}>
                    <DashboardCanvas
                        mode={mode}
                        widgets={layout.widgets}
                        selectedWidgetId={selectedWidgetId}
                        snapToGrid={snapToGrid}
                        onSelectWidget={setSelectedWidgetId}
                        onUpdateWidget={handleUpdateWidget}
                        onDeleteWidget={handleDeleteWidget}
                        onAddWidget={handleAddWidget}
                        onAddWidgets={handleAddWidgets}
                        outputs={outputs}
                        nodes={nodes}
                        onInputChange={onInputChange}
                        viewBounds={currentViewport}
                        onUpdateViewBounds={handleUpdateViewBounds}
                    />
                </div>
            </div>

            {/* Right Panel - Design Mode Only */}
            {mode === "design" && (
                <>
                    <button
                        className="panel-collapse-btn right"
                        style={{ right: rightPanelCollapsed ? 0 : rightPanelWidth, position: 'absolute', top: '50%', zIndex: 100 }}
                        onClick={() => setRightPanelCollapsed(!rightPanelCollapsed)}
                        title={rightPanelCollapsed ? "Expand Properties" : "Collapse Properties"}
                    >
                        {rightPanelCollapsed ? <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M15.41 7.41L14 6l-6 6 6 6 1.41-1.41L10.83 12z" /></svg> : <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor"><path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" /></svg>}
                    </button>

                    <aside
                        className={`side-panel right-panel ${rightPanelCollapsed ? "collapsed" : ""}`}
                        style={{ width: rightPanelCollapsed ? 0 : rightPanelWidth, height: '100%', top: 0, position: 'relative', background: 'var(--bg-surface)' }}
                    >
                        {!rightPanelCollapsed && (
                            <>
                                <div
                                    className="resize-handle left"
                                    onMouseDown={startResizingRight}
                                />
                                {selectedWidgetId === "view-bounds" ? (
                                    <DashboardViewportProperties
                                        viewport={currentViewport}
                                        onUpdate={(updates) => handleUpdateViewBounds({ ...currentViewport, ...updates })}
                                        onFitToScreen={handleFitToScreen}
                                    />
                                ) : selectedWidget ? (
                                    <DashboardProperties
                                        widget={selectedWidget}
                                        onUpdate={handleUpdateWidget}
                                        publishedItems={publishedItems}
                                        onInputChange={onInputChange}
                                        value={(() => {
                                            if (selectedWidget && selectedWidget.nodeId && selectedWidget.portName) {
                                                // Resolution logic similar to WidgetContent
                                                // 1. Outputs
                                                if (outputs[selectedWidget.nodeId] && (outputs[selectedWidget.nodeId] as any)[selectedWidget.portName] !== undefined) {
                                                    return (outputs[selectedWidget.nodeId] as any)[selectedWidget.portName];
                                                }
                                                // 2. Node Last Outputs
                                                const node = nodes.find(n => n.id === selectedWidget.nodeId);
                                                if (node?.data.last_outputs) {
                                                    return node.data.last_outputs[selectedWidget.portName];
                                                }
                                                // 3. Node Inputs (if bound-input)
                                                if (node && node.data.inputValues && node.data.inputValues[selectedWidget.portName] !== undefined && selectedWidget.type === 'bound-input') {
                                                    return node.data.inputValues[selectedWidget.portName];
                                                }
                                            }
                                            return null;
                                        })()}
                                    />
                                ) : (
                                    <div style={{ padding: '20px', textAlign: 'center', color: 'var(--text-muted)', fontSize: '13px' }}>
                                        Select a widget to edit properties
                                    </div>
                                )}
                            </>
                        )}
                    </aside>
                </>
            )}
        </div>
    );
};

export default DashboardView;
