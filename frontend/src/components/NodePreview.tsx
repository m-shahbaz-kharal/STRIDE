import React from "react";
import { NodeTypeDefinition } from "../types";

interface NodePreviewProps {
    nodeType: NodeTypeDefinition;
}

const NodePreview = ({ nodeType }: NodePreviewProps) => {
    // Calculate initial size based on ports (matches MIN_WIDTH/MIN_HEIGHT in BlueprintNode)
    const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
    const MIN_WIDTH = 160;
    const MIN_HEIGHT = 52 + maxPorts * 24;

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
                    {nodeType.input_ports.map((port, index) => (
                        <div key={`in-${port}-${index}`} className="node-port node-port-input">
                            <div className="node-handle react-flow__handle" style={{ left: -4 }} />
                            <span>{port}</span>
                        </div>
                    ))}
                </div>
                <div className="node-port-column">
                    {nodeType.output_ports.map((port, index) => (
                        <div key={`out-${port}-${index}`} className="node-port node-port-output">
                            <span className="node-port-label">{port}</span>
                            <div className="node-handle react-flow__handle" style={{ right: -4 }} />
                        </div>
                    ))}
                </div>
            </div>
        </div>
    );
};

export default NodePreview;
