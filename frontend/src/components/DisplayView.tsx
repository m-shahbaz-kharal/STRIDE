
import React, { useEffect, useMemo, useState } from "react";
import { Node, useReactFlow } from "reactflow";
import { BlueprintNodeData } from "../types";

interface DisplayViewProps {
    nodes: Node<BlueprintNodeData>[];
    outputs: Record<string, unknown>;
    onJumpToNode?: (nodeId: string) => void;
}

type DisplayItem = {
    nodeId: string;
    nodeName: string;
    section: string;
    title: string;
    value: unknown;
    ts: number; // timestamp for re-renders or ordering
};

const DisplayView: React.FC<DisplayViewProps> = ({ nodes, outputs, onJumpToNode }) => {
    const [refreshToken, setRefreshToken] = useState(0);
    const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
    const { setCenter, zoomTo } = useReactFlow();

    const toggleSection = (section: string) => {
        setCollapsedSections((prev) => {
            const next = new Set(prev);
            if (next.has(section)) next.delete(section);
            else next.add(section);
            return next;
        });
    };

    const handleJump = (nodeId: string) => {
        if (onJumpToNode) {
            onJumpToNode(nodeId);
        }
        // Also try to center purely via internal ReactFlow hook if parent doesn't handle it fully
        const node = nodes.find(n => n.id === nodeId);
        if (node) {
            setCenter(node.position.x, node.position.y, { zoom: 1.2, duration: 800 });
        }
    };


    const formatValue = (val: unknown): string => {
        if (val === null) return "null";
        if (val === undefined) return "undefined";
        if (typeof val === "string") return val;
        if (typeof val === "number" || typeof val === "boolean") return String(val);
        return JSON.stringify(val, null, 2);
    };

    // Collect outputs specifically from "general.to_display" nodes
    const { sections, hasStreams } = useMemo(() => {
        const items: DisplayItem[] = [];
        let foundStreams = false;

        for (const node of nodes) {
            // Only process "To Display" nodes
            if (node.data.nodeType !== "general.to_display") continue;

            const nodeOutputs = node.data.last_outputs;
            if (!nodeOutputs) continue;

            // Check for expected keys from ToDisplayNode
            // { section: str, title: str, value: any }
            const section = String(nodeOutputs.section || "Main");
            const title = String(nodeOutputs.title || "Output");
            const value = nodeOutputs.value;

            items.push({
                nodeId: node.id,
                nodeName: node.data.displayName,
                section,
                title,
                value,
                ts: Date.now(),
            });

            // Heuristic to detect if we need high-frequency refresh (streams)
            if (value && typeof value === "object" && (value as any)._type === "StreamResource") {
                foundStreams = true;
            }
        }

        // Group by section
        const grouped: Record<string, DisplayItem[]> = {};
        for (const item of items) {
            if (!grouped[item.section]) grouped[item.section] = [];
            grouped[item.section].push(item);
        }

        // Sort sections alphabetically or by some priority? "Main" first?
        // keys sorted:
        const sortedKeys = Object.keys(grouped).sort((a, b) => {
            if (a === "Main") return -1;
            if (b === "Main") return 1;
            return a.localeCompare(b);
        });

        const sortedSections: { name: string; items: DisplayItem[] }[] = sortedKeys.map(k => ({
            name: k,
            items: grouped[k]
        }));

        return { sections: sortedSections, hasStreams: foundStreams };
    }, [nodes]);

    // Heartbeat refresh for stream snapshots
    // We keep this mechanism but only if we detected stream-like content
    useEffect(() => {
        // We can just always run this at 1000ms if ANY content is there, or be smarter.
        // The previous code had `if (streams.length === 0) return;`
        // We'll trust React's optimization.
        const interval = window.setInterval(() => setRefreshToken((prev) => prev + 1), 1000);
        return () => window.clearInterval(interval);
    }, []); // Always run it, or depend on hasStreams? 
    // Let's rely on standard interval for now.

    const hasContent = sections.length > 0;

    if (!hasContent) {
        return (
            <div className="outputs-view">
                <div className="outputs-empty">
                    <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor" style={{ opacity: 0.3 }}>
                        <path d="M21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm0 16H3V5h18v14zM21 3H3c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h18c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2z" />
                        <path d="M8 15c0-1.66 1.34-3 3-3 .55 0 1.05.15 1.48.41L13.74 11A5.99 5.99 0 0 0 11 10c-3.31 0-6 2.69-6 6h2c0-2.21 1.79-4 4-4 .69 0 1.33.17 1.9.46l1.39-1.57A5.92 5.92 0 0 0 11 10z" />
                    </svg>
                    <p>No display items</p>
                    <p className="outputs-empty-hint">Add "To Display" nodes to your graph to see results here.</p>
                </div>
            </div>
        );
    }

    return (
        <div className="outputs-view">
            {sections.map(section => (
                <section key={section.name} className="outputs-section">
                    <button
                        type="button"
                        className="outputs-header"
                        onClick={() => toggleSection(section.name)}
                        aria-expanded={!collapsedSections.has(section.name)}
                    >
                        <div className="outputs-header-title">
                            <p className="eyebrow">Section</p>
                            <h3>{section.name}</h3>
                        </div>
                        <div className="outputs-header-meta">
                            <span className="outputs-count">{section.items.length}</span>
                            <span className={`outputs-chevron ${collapsedSections.has(section.name) ? "collapsed" : ""}`} aria-hidden="true">
                                <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                    <path d="M5 7.5L10 12.5L15 7.5" />
                                </svg>
                            </span>
                        </div>
                    </button>

                    {!collapsedSections.has(section.name) && (
                        <div className="outputs-display-grid">
                            {section.items.map((item, idx) => (
                                <DisplayCard
                                    key={`${item.nodeId}-${idx}`}
                                    item={item}
                                    refreshToken={refreshToken}
                                    onJump={() => handleJump(item.nodeId)}
                                />
                            ))}
                        </div>
                    )}
                </section>
            ))}
        </div>
    );
};

// Sub-component for individual display cards to keep logic clean
const DisplayCard: React.FC<{
    item: DisplayItem;
    refreshToken: number;
    onJump: () => void;
}> = ({ item, refreshToken, onJump }) => {

    // Determine content type
    const val = item.value;
    let content: React.ReactNode = null;

    if (val && typeof val === "object" && (val as any)._type === "StreamResource") {
        // It's a stream object
        const stream = val as any;
        // Use the same streaming URL pattern as before
        // Assuming stream.stream_id exists
        content = (
            <div className="output-card__body media-container">
                <img
                    src={`/api/streams/${stream.stream_id}/frame?ts=${refreshToken}`}
                    alt={item.title}
                    className="output-card__media"
                    onError={(e) => {
                        const target = e.target as HTMLImageElement;
                        target.style.opacity = "0.45";
                    }}
                />
                <div className="media-overlay live">LIVE</div>
            </div>
        );
    } else if (typeof val === "string" && val.startsWith("data:image")) {
        // Base64 image
        content = (
            <div className="output-card__body media-container">
                <img
                    src={val}
                    alt={item.title}
                    className="output-card__media"
                />
            </div>
        );
    } else if (typeof val === "string") {
        content = <pre className="output-value-body text-content">{val}</pre>;
    } else {
        // Fallback JSON
        content = <pre className="output-value-body json-content">{JSON.stringify(val, null, 2)}</pre>;
    }

    return (
        <div className="output-display-card">
            <div className="display-card-header">
                <span className="display-card-title">{item.title}</span>
                <button className="display-jump-btn" title="Jump to Node" onClick={(e) => { e.stopPropagation(); onJump(); }}>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="12" cy="12" r="10" />
                        <circle cx="12" cy="12" r="3" />
                    </svg>
                </button>
            </div>
            {content}
            <div className="display-card-footer">
                <span className="mono-xs">{item.nodeId}</span>
            </div>
        </div>
    );
};

export default React.memo(DisplayView);
