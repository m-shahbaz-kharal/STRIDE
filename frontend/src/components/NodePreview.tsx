import React from "react";
import { NodeTypeDefinition, TypeDescriptor } from "../types";
import { formatPortTypeLabel, getCategoryColor, getPortTypeColor } from "../graph/utils";

interface NodePreviewProps {
    nodeType: NodeTypeDefinition;
}

const NodePreview = ({ nodeType }: NodePreviewProps) => {
    // Calculate initial size based on ports (mirrors BlueprintNode sizing)
    const maxPorts = Math.max(nodeType.input_ports.length, nodeType.output_ports.length);
    const MIN_WIDTH = 260;
    const extraInputRows = nodeType.node_type === "core.container.make_array" ? 1 : 0;
    const MIN_HEIGHT = 70 + (maxPorts + extraInputRows) * 42 + 8;
    const inputPortTypes = nodeType.input_port_types || {};
    const outputPortTypes = nodeType.output_port_types || {};
    const getTypeKind = (portType: TypeDescriptor | string | undefined) =>
        typeof portType === "string" ? portType.toLowerCase() : portType?.kind ?? "any";

    const category = nodeType.category || nodeType.node_type.split(".")[0] || "Other";
    const categoryColor = getCategoryColor(category);

    return (
        <div
            className="blueprint-node"
            style={{
                width: MIN_WIDTH,
                height: MIN_HEIGHT,
                position: "relative",
                transform: "scale(1)", // Ensure it renders at 1:1 scale for the drag image
                transformOrigin: "top left",
                ["--category-color" as string]: categoryColor,
            }}
        >
            <div className="node-header">
                <div className="node-title-section">
                    <strong>{nodeType.display_name}</strong>
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
                        const portType = inputPortTypes?.[port] as TypeDescriptor | string | undefined;
                        const color = getPortTypeColor(portType);
                        const isControl = getTypeKind(portType) === "control";
                        const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
                        const controlLabel = port.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                        return (
                            <div
                                key={`in-${port}-${index}`}
                                className={`node-port node-port-input ${isControl ? "control-port" : ""}`}
                            >
                                <div
                                    className={`node-handle react-flow__handle ${isControl ? "control-handle" : ""}`}
                                    style={{ left: -4, ["--handle-color" as string]: color }}
                                >
                                    {isControl && (
                                        <svg className="control-handle-icon" viewBox="0 0 24 24" aria-hidden="true">
                                            <path d="M8 5v14l11-7z" />
                                        </svg>
                                    )}
                                </div>
                                {!isControl && (
                                    <div className="node-port-label-group">
                                        <span className="node-port-name">{port}</span>
                                        <span
                                            className="port-type-pill"
                                            style={{ ["--port-color" as string]: color }}
                                        >
                                            {formatPortTypeLabel(portType)}
                                        </span>
                                    </div>
                                )}
                                {showControlLabel && (
                                    <span className="control-port-label">{controlLabel}</span>
                                )}
                            </div>
                        );
                    })}
                </div>
                <div className="node-port-column">
                    {nodeType.output_ports.map((port, index) => {
                        const portType = outputPortTypes?.[port] as TypeDescriptor | string | undefined;
                        const color = getPortTypeColor(portType);
                        const isControl = getTypeKind(portType) === "control";
                        const showControlLabel = isControl && port !== "control_in" && port !== "control_out";
                        const controlLabel = port.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
                        return (
                            <div
                                key={`out-${port}-${index}`}
                                className={`node-port node-port-output ${isControl ? "control-port" : ""}`}
                            >
                                {!isControl && (
                                    <div className="node-port-label-group">
                                        <span className="node-port-label">{port}</span>
                                        <span
                                            className="port-type-pill"
                                            style={{ ["--port-color" as string]: color }}
                                        >
                                            {formatPortTypeLabel(portType)}
                                        </span>
                                    </div>
                                )}
                                {showControlLabel && (
                                    <span className="control-port-label">{controlLabel}</span>
                                )}
                                <div
                                    className={`node-handle react-flow__handle ${isControl ? "control-handle" : ""}`}
                                    style={{ right: -4, ["--handle-color" as string]: color }}
                                >
                                    {isControl && (
                                        <svg className="control-handle-icon" viewBox="0 0 24 24" aria-hidden="true">
                                            <path d="M8 5v14l11-7z" />
                                        </svg>
                                    )}
                                </div>
                            </div>
                        );
                    })}
                </div>
            </div>
        </div>
    );
};

export default NodePreview;
