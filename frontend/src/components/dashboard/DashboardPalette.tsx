import React, { useState, useMemo } from "react";
import { DashboardWidget, PublishedPortData, TypeKind } from "../../types";

// Category icon component (reused from NodePalette style)
const ChevronIcon = ({ collapsed }: { collapsed: boolean }) => (
    <svg
        className="category-icon"
        width="12"
        height="12"
        viewBox="0 0 24 24"
        fill="currentColor"
        style={{ transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
    >
        <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
    </svg>
);

interface DashboardPaletteProps {
    publishedItems: { nodeId: string; nodeName: string; port: PublishedPortData }[];
    onAddWidget: (widget: DashboardWidget) => void;
    onJumpToNode?: (nodeId: string) => void;
    onUnpublish?: (nodeId: string, portId: string, direction: "input" | "output") => void;
}

const DashboardPalette: React.FC<DashboardPaletteProps> = ({ publishedItems, onAddWidget, onJumpToNode, onUnpublish }) => {
    const [query, setQuery] = useState("");
    const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

    // Toggle Collapse
    const toggleCategory = (category: string) => {
        setCollapsedCategories((prev) => {
            const newSet = new Set(prev);
            if (newSet.has(category)) {
                newSet.delete(category);
            } else {
                newSet.add(category);
            }
            return newSet;
        });
    };

    // Prepare Categories
    const widgets = useMemo(() => {
        const lowerQuery = query.toLowerCase();

        // Define Core Items
        const coreItems = [
            { type: 'label', label: 'Text Label', description: 'Simple text label' },
            { type: 'panel', label: 'Panel', description: 'Background container' },
        ];

        // Filter Function
        const matchesInfo = (label: string, desc: string) =>
            label.toLowerCase().includes(lowerQuery) || desc.toLowerCase().includes(lowerQuery);

        // Grouping
        const groups: Record<string, {
            id: string,
            label: string,
            desc: string,
            onClick: () => void,
            type: string,
            w: number,
            h: number,
            nodeId?: string,
            portName?: string,
            inputType?: TypeKind
        }[]> = {
            "Core Widgets": [],
            "Inputs": [],
            "Outputs": []
        };

        // Add Core
        coreItems.forEach(item => {
            if (matchesInfo(item.label, item.description)) {
                groups["Core Widgets"].push({
                    id: `core-${item.type}`,
                    label: item.label,
                    desc: item.description,
                    type: item.type,
                    w: item.type === 'container' ? 400 : 200,
                    h: item.type === 'container' ? 300 : 40,
                    onClick: () => {
                        onAddWidget({
                            id: `widget-${Date.now()}`,
                            type: item.type as any,
                            label: item.label,
                            x: 0, y: 0,
                            w: item.type === 'container' ? 400 : 200,
                            h: item.type === 'container' ? 300 : 40,
                            style: {}
                        });
                    }
                });
            }
        });

        // Add Inputs/Outputs
        publishedItems.forEach(item => {
            const category = item.port.direction === "input" ? "Inputs" : "Outputs";
            const label = item.port.alias;
            const desc = `${item.nodeName} • ${item.port.direction}`;

            if (matchesInfo(label, desc)) {
                groups[category].push({
                    id: `pub-${item.nodeId}-${item.port.portId}`,
                    label: label,
                    desc: desc,
                    type: item.port.direction === "input" ? "bound-input" : "bound-output",
                    w: item.port.direction === "input" ? 240 : 300,
                    h: item.port.direction === "input" ? 80 : 200,
                    nodeId: item.nodeId,
                    portName: item.port.portId,
                    inputType: item.port.kind,
                    onClick: () => {
                        onAddWidget({
                            id: `widget-${Date.now()}`,
                            type: item.port.direction === "input" ? "bound-input" : "bound-output",
                            label: label,
                            x: 0, y: 0,
                            w: item.port.direction === "input" ? 240 : 300,
                            h: item.port.direction === "input" ? 80 : 200,
                            nodeId: item.nodeId,
                            portName: item.port.portId,
                            inputType: item.port.kind,
                            style: {}
                        });
                    }
                });
            }
        });

        return groups;
    }, [query, publishedItems, onAddWidget]);

    const hasResults = Object.values(widgets).some(g => g.length > 0);

    return (
        <div className="palette-panel">
            <div className="palette-header">
                <h3>UI Elements</h3>
            </div>

            <div className="palette-search">
                <input
                    placeholder="Search elements..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
            </div>

            <div className="palette-list">
                {Object.entries(widgets).map(([category, items]) => {
                    if (items.length === 0) return null;
                    const isCollapsed = collapsedCategories.has(category);

                    return (
                        <div key={category} className="palette-category">
                            <button
                                type="button"
                                className={`category-header ${isCollapsed ? "collapsed" : ""}`}
                                onClick={() => toggleCategory(category)}
                            >
                                <ChevronIcon collapsed={isCollapsed} />
                                <span>{category}</span>
                                <span className="category-count">{items.length}</span>
                            </button>

                            <div className={`category-items ${isCollapsed ? "collapsed" : ""}`}>
                                {items.map((item) => {
                                    const isPublishedItem = category !== "Core Widgets";
                                    const publishedItem = isPublishedItem ? publishedItems.find(
                                        p => p.nodeId === item.nodeId && p.port.portId === item.portName
                                    ) : null;

                                    return (
                                        <div
                                            key={item.id}
                                            className="palette-item palette-item-with-actions"
                                            draggable
                                            onDragStart={(e) => {
                                                // Create a widget object to pass
                                                const widgetData = {
                                                    type: item.type,
                                                    label: item.label,
                                                    w: item.w,
                                                    h: item.h,
                                                    nodeId: item.nodeId,
                                                    portName: item.portName,
                                                    inputType: item.inputType,
                                                    style: {}
                                                };
                                                e.dataTransfer.setData("application/reactflow-widget", JSON.stringify(widgetData));
                                                e.dataTransfer.effectAllowed = "copy";
                                            }}
                                            title={item.desc}
                                            style={{ position: 'relative' }}
                                        >
                                            <div
                                                className="palette-item-content"
                                                onClick={item.onClick}
                                                style={{ flex: 1, display: 'flex', alignItems: 'center', cursor: 'pointer', paddingRight: isPublishedItem ? '60px' : '8px' }}
                                            >
                                                <span className="palette-item-name">{item.label}</span>
                                            </div>

                                            {isPublishedItem && (
                                                <div
                                                    className="palette-item-actions"
                                                    style={{
                                                        position: 'absolute',
                                                        right: '4px',
                                                        top: '50%',
                                                        transform: 'translateY(-50%)',
                                                        display: 'flex',
                                                        gap: '4px',
                                                        alignItems: 'center'
                                                    }}
                                                >
                                                    {/* View Source Icon */}
                                                    {onJumpToNode && item.nodeId && (
                                                        <button
                                                            className="palette-action-btn"
                                                            title="View Source Node"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                onJumpToNode(item.nodeId!);
                                                            }}
                                                            style={{
                                                                background: 'transparent',
                                                                border: 'none',
                                                                cursor: 'pointer',
                                                                color: 'var(--text-muted)',
                                                                padding: '4px',
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                justifyContent: 'center'
                                                            }}
                                                        >
                                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                                <polyline points="16 18 22 12 16 6"></polyline>
                                                                <polyline points="8 6 2 12 8 18"></polyline>
                                                            </svg>
                                                        </button>
                                                    )}

                                                    {/* Unpublish Icon (Rightmost, hover only) */}
                                                    {onUnpublish && item.nodeId && item.portName && publishedItem && (
                                                        <button
                                                            className="palette-action-btn"
                                                            title="Unpublish"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                onUnpublish(item.nodeId!, item.portName!, publishedItem.port.direction);
                                                            }}
                                                            style={{
                                                                background: 'transparent',
                                                                border: 'none',
                                                                cursor: 'pointer',
                                                                color: 'var(--text-muted)',
                                                                padding: '4px',
                                                                display: 'flex',
                                                                alignItems: 'center',
                                                                justifyContent: 'center'
                                                            }}
                                                        >
                                                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                                                <line x1="18" y1="6" x2="6" y2="18"></line>
                                                                <line x1="6" y1="6" x2="18" y2="18"></line>
                                                            </svg>
                                                        </button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    );
                                })}
                            </div>
                        </div>
                    );
                })}

                {!hasResults && (
                    <p className="palette-empty">
                        No elements match "{query}"
                    </p>
                )}
            </div>
        </div>
    );
};

export default DashboardPalette;
