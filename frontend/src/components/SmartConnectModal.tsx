import React, { useEffect, useMemo, useRef, useState } from "react";
import { NodeTypeDefinition } from "../types";

interface SmartConnectModalProps {
    isOpen: boolean;
    position: { x: number; y: number };
    onClose: () => void;
    onSelect: (nodeType: NodeTypeDefinition) => void;
    nodeTypes: NodeTypeDefinition[];
    sourceHandleType?: "source" | "target";
}

// Helper to get category icon (simple mapping for now)
const getCategoryIcon = (category: string) => {
    const map: Record<string, string> = {
        Math: "+",
        Logic: "&",
        Strings: "\"",
        Variables: "$",
        Control: ">",
        Literal: "#",
        Containers: "[]",
        Utility: "*",
    };
    return map[category] || "?";
};

const SmartConnectModal = ({
    isOpen,
    position,
    onClose,
    onSelect,
    nodeTypes,
    sourceHandleType,
}: SmartConnectModalProps) => {
    const [query, setQuery] = useState("");
    const [selectedIndex, setSelectedIndex] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);
    const listRef = useRef<HTMLDivElement>(null);
    const modalRef = useRef<HTMLDivElement>(null);

    // Parse and prioritize nodes
    const filteredNodes = useMemo(() => {
        const normalizedQuery = query.trim().toLowerCase();

        // 1. Filter
        let nodes = nodeTypes;
        if (normalizedQuery) {
            nodes = nodeTypes.filter((node) =>
                node.display_name.toLowerCase().includes(normalizedQuery) ||
                node.node_type.toLowerCase().includes(normalizedQuery)
            );

            const scoreMatch = (text: string) => {
                const normalizedText = text.toLowerCase();
                if (normalizedText === normalizedQuery) return 0;

                const words = normalizedText.split(/[^a-z0-9]+/).filter(Boolean);
                if (words[0] === normalizedQuery) return 1;
                if (words.includes(normalizedQuery)) return 2;
                if (normalizedText.startsWith(normalizedQuery)) return 3;
                if (words.some((word) => word.startsWith(normalizedQuery))) return 4;
                if (normalizedText.includes(normalizedQuery)) return 5;
                return 6;
            };

            const scoreNode = (node: NodeTypeDefinition) => {
                const displayScore = scoreMatch(node.display_name);
                if (displayScore < 6) return displayScore;
                const typeScore = scoreMatch(node.node_type);
                return typeScore < 6 ? typeScore + 10 : 20;
            };

            nodes = [...nodes].sort((a, b) => {
                const aScore = scoreNode(a);
                const bScore = scoreNode(b);
                if (aScore !== bScore) return aScore - bScore;
                return a.display_name.localeCompare(b.display_name);
            });
        }

        // 2. Sort/Prioritize based on context (if no query)
        if (!normalizedQuery && sourceHandleType) {
            nodes = [...nodes].sort((a, b) => {
                const aType = a.node_type.toLowerCase();
                const bType = b.node_type.toLowerCase();

                // If dragging from Source (Output), prioritize Processors/Displays
                if (sourceHandleType === "source") {
                    const aScore = aType.includes("output") || aType.includes("display") ? 2 : 1;
                    const bScore = bType.includes("output") || bType.includes("display") ? 2 : 1;
                    return bScore - aScore;
                }

                // If dragging from Target (Input), prioritize Inputs/Constants
                if (sourceHandleType === "target") {
                    const aScore = aType.includes("input") || aType.includes("constant") ? 2 : 1;
                    const bScore = bType.includes("input") || bType.includes("constant") ? 2 : 1;
                    return bScore - aScore;
                }

                return 0;
            });
        }

        return nodes;
    }, [nodeTypes, query, sourceHandleType]);

    // Reset selection when query changes
    useEffect(() => {
        setSelectedIndex(0);
    }, [query, filteredNodes]);

    // Auto-focus input when opened
    useEffect(() => {
        if (isOpen) {
            setTimeout(() => inputRef.current?.focus(), 50);
            setQuery("");
            setSelectedIndex(0);
        }
    }, [isOpen]);

    // Handle keyboard navigation
    useEffect(() => {
        if (!isOpen) return;

        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "ArrowDown") {
                e.preventDefault();
                setSelectedIndex((prev) => Math.min(prev + 1, filteredNodes.length - 1));
            } else if (e.key === "ArrowUp") {
                e.preventDefault();
                setSelectedIndex((prev) => Math.max(prev - 1, 0));
            } else if (e.key === "Enter") {
                e.preventDefault();
                if (filteredNodes[selectedIndex]) {
                    onSelect(filteredNodes[selectedIndex]);
                }
            } else if (e.key === "Escape") {
                e.preventDefault();
                onClose();
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [isOpen, filteredNodes, selectedIndex, onSelect, onClose]);

    // Close when clicking outside the modal
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: MouseEvent | TouchEvent) => {
            const target = e.target as Node | null;
            if (modalRef.current && target instanceof Node && !modalRef.current.contains(target as Node)) {
                onClose();
            }
        };
        document.addEventListener("mousedown", handler);
        document.addEventListener("touchstart", handler);
        return () => {
            document.removeEventListener("mousedown", handler);
            document.removeEventListener("touchstart", handler);
        };
    }, [isOpen, onClose]);

    // Scroll selected item into view
    useEffect(() => {
        if (listRef.current) {
            const selectedElement = listRef.current.children[selectedIndex] as HTMLElement;
            if (selectedElement) {
                selectedElement.scrollIntoView({ block: "nearest" });
            }
        }
    }, [selectedIndex]);

    if (!isOpen) return null;

    // Calculate position to keep within viewport
    const modalWidth = 320;
    const modalHeight = 400; // Approx max height
    const padding = 20;

    // Initial position: Center vertically on the drop point (assuming ~50px header height)
    let top = position.y - 25;

    // Horizontal position based on connection direction
    let left = position.x;

    if (sourceHandleType === "target") {
        // Dragging from Input -> Output (Right to Left)
        // Place modal to the left of the drop point
        left = position.x - modalWidth;
    } else {
        // Dragging from Output -> Input (Left to Right) or default
        // Place modal to the right of the drop point
        left = position.x;
    }

    // Viewport boundary checks
    if (left + modalWidth > window.innerWidth - padding) {
        // If it goes off the right edge, flip to left
        left = position.x - modalWidth;
    }
    if (left < padding) {
        // If it goes off the left edge, flip to right
        left = position.x;
    }

    if (top + modalHeight > window.innerHeight - padding) {
        top = window.innerHeight - modalHeight - padding;
    }
    if (top < padding) {
        top = padding;
    }

    return (
        <div
            className="smart-connect-modal premium"
            style={{
                position: "fixed",
                left,
                top,
                zIndex: 1000,
            }}
            ref={modalRef}
            onClick={(e) => e.stopPropagation()}
        >
            <div className="smart-connect-header">
                <div className="search-icon">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <circle cx="11" cy="11" r="8" />
                        <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </svg>
                </div>
                <input
                    ref={inputRef}
                    type="text"
                    placeholder="Type to search..."
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                />
                <div className="shortcut-hint">ESC to close</div>
            </div>

            <div className="smart-connect-list" ref={listRef}>
                {filteredNodes.map((node, index) => {
                    const category = node.category || "Other";
                    return (
                        <div
                            key={node.node_type}
                            className={`smart-connect-item ${index === selectedIndex ? "selected" : ""}`}
                            onClick={() => onSelect(node)}
                            onMouseEnter={() => setSelectedIndex(index)}
                        >
                            <div className="item-icon">{getCategoryIcon(category)}</div>
                            <div className="item-content">
                                <div className="node-title-row">
                                    <span className="node-category">{category}</span>
                                    <span className="node-name">{node.display_name}</span>
                                </div>
                                <span className="node-desc">{node.description}</span>
                            </div>
                            {index === selectedIndex && <span className="enter-hint">↵</span>}
                        </div>
                    );
                })}
                {filteredNodes.length === 0 && (
                    <div className="smart-connect-empty">
                        <div className="empty-icon">?</div>
                        <div>No matching nodes found</div>
                    </div>
                )}
            </div>
        </div>
    );
};

export default SmartConnectModal;

