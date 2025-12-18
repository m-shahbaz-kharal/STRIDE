import React from "react";
import { NodeTypeDefinition } from "../types";

interface NodePreviewProps {
    nodeType: NodeTypeDefinition;
}

const PREVIEW_PORT_COLORS: Record<string, string> = {
    number: "#4a9eff",
    image: "#e85aad",
    stream: "#0fb5a9",
    url: "#7c3aed",
    boolean: "#f59e0b",
    string: "#10b981",
    any: "#94a3b8",
};

const getPreviewPortColor = (type?: string): string => {
    const key = type?.toLowerCase() || "any";
    return PREVIEW_PORT_COLORS[key] || PREVIEW_PORT_COLORS.any;
};

const formatPortTypeLabel = (type?: string): string => {
    if (!type) return "Any";
    const label = type.toLowerCase().replace(/_/g, " ");
    return label.charAt(0).toUpperCase() + label.slice(1);
};

const NodePreview = ({ nodeType }: NodePreviewProps) => {
    // Calculate initial size based on ports (mirrors BlueprintNode sizing)
    const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
    const MIN_WIDTH = 220;
    const MIN_HEIGHT = 70 + maxPorts * 34;
    const inputPortTypes = nodeType.input_port_types || {};
    const outputPortTypes = nodeType.output_port_types || {};

    return (
        <div
            className="blueprint-node"
            style={{
                width: MIN_WIDTH,
                height: MIN_HEIGHT,
                position: "relative",
                transform: "scale(1)", // Ensure it renders at 1:1 scale for the drag image
                transformOrigin: "top left",
            }}
        >
            <div className="node-header">
                <div className="node-title-section">
                    <strong>{nodeType.display_name}</strong>
                    <span className="node-type-label">{nodeType.node_type}</span>
                </div>
                <div className="node-header-right">
                    {/* Mock action buttons for visual fidelity */}
                    <div className="node-action-btn nodrag">
                        <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M8 5v14l11-7z" />
                        </svg>
                    </div>
                </div>
            </div>

            <div className="node-ports">
                <div className="node-port-column">
                    {nodeType.input_ports.map((port, index) => {
                        const portType = inputPortTypes?.[port] || "any";
                        const color = getPreviewPortColor(portType);
                        return (
                            <div key={`in-${port}-${index}`} className="node-port node-port-input">
                                <div
                                    className="node-handle react-flow__handle"
                                    style={{ left: -4, ["--handle-color" as string]: color }}
                                />
                                <div className="node-port-label-group">
                                    <span className="node-port-name">{port}</span>
                                    <span
                                        className="port-type-pill"
                                        style={{ ["--port-color" as string]: color }}
                                    >
                                        {formatPortTypeLabel(portType)}
                                    </span>
                                </div>
                            </div>
                        );
                    })}
                </div>
                <div className="node-port-column">
                    {nodeType.output_ports.map((port, index) => {
                        const portType = outputPortTypes?.[port] || "any";
                        const color = getPreviewPortColor(portType);
                        return (
                            <div key={`out-${port}-${index}`} className="node-port node-port-output">
                                <div className="node-port-label-group">
                                    <span className="node-port-label">{port}</span>
                                    <span
                                        className="port-type-pill"
                                        style={{ ["--port-color" as string]: color }}
                                    >
                                        {formatPortTypeLabel(portType)}
                                    </span>
                                </div>
                                <div
                                    className="node-handle react-flow__handle"
                                    style={{ right: -4, ["--handle-color" as string]: color }}
                                />
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default NodePreview;
