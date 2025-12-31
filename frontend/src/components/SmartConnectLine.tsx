import React from "react";
import { ReactFlowInstance } from "reactflow";

interface SmartConnectLineProps {
    isOpen: boolean;
    source: {
        nodeId: string;
        handleId: string;
        type: "source" | "target";
    } | null;
    position: { x: number; y: number };
    getHandlePosition: (
        nodeId: string,
        handleId: string,
        type: "source" | "target"
    ) => { x: number; y: number } | null;
    reactFlowInstance: ReactFlowInstance | null;
}

const SmartConnectLine: React.FC<SmartConnectLineProps> = ({
    isOpen,
    source,
    position,
    getHandlePosition,
    reactFlowInstance,
}) => {
    if (!isOpen || !source || !reactFlowInstance) return null;

    const startFlow = getHandlePosition(source.nodeId, source.handleId, source.type);
    if (!startFlow) return null;

    // Convert start point to screen coordinates
    const start = reactFlowInstance.flowToScreenPosition(startFlow);
    const end = position;

    const isSourceHandle = source.type === "source";
    const startX = start.x;
    const startY = start.y;
    const endX = end.x;
    const endY = end.y;

    const dist = Math.abs(endX - startX) * 0.5;
    const cp1x = isSourceHandle ? startX + dist : startX - dist;
    const cp1y = startY;
    const cp2x = isSourceHandle ? endX - dist : endX + dist;
    const cp2y = endY;

    const path = `M ${startX} ${startY} C ${cp1x} ${cp1y} ${cp2x} ${cp2y} ${endX} ${endY}`;

    return (
        <svg
            style={{
                position: "absolute",
                top: 0,
                left: 0,
                width: "100%",
                height: "100%",
                pointerEvents: "none",
                zIndex: 999,
                overflow: "visible",
            }}
        >
            <path
                d={path}
                stroke="#4a9eff"
                strokeWidth="2"
                fill="none"
                strokeDasharray="5,5"
                className="smart-connect-line"
            />
        </svg>
    );
};

export default SmartConnectLine;
