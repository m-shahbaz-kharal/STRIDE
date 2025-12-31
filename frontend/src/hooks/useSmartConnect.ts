import { useCallback, useState } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, NodeTypeDefinition, TypeDescriptor } from "../types";

interface SmartConnectMenuState {
    isOpen: boolean;
    position: { x: number; y: number };
    flowPosition: { x: number; y: number };
    source: { nodeId: string; handleId: string; type: "source" | "target" } | null;
    sourcePortKind?: string;
}

interface UseSmartConnectOptions {
    getPortTypeForHandle: (nodeId: string, handleId: string, role: "source" | "target") => TypeDescriptor;
    arePortTypesCompatible: (sourceType: TypeDescriptor | string | undefined, targetType: TypeDescriptor | string | undefined) => boolean;
}

export const useSmartConnect = ({
    getPortTypeForHandle,
    arePortTypesCompatible,
}: UseSmartConnectOptions) => {
    const [smartConnectMenu, setSmartConnectMenu] = useState<SmartConnectMenuState>({
        isOpen: false,
        position: { x: 0, y: 0 },
        flowPosition: { x: 0, y: 0 },
        source: null,
        sourcePortKind: undefined,
    });

    const openSmartConnect = useCallback((
        screenPosition: { x: number; y: number },
        flowPosition: { x: number; y: number },
        source: { nodeId: string; handleId: string; type: "source" | "target" },
        sourcePortType?: TypeDescriptor
    ) => {
        setSmartConnectMenu({
            isOpen: true,
            position: screenPosition,
            flowPosition,
            source,
            sourcePortKind: sourcePortType?.kind,
        });
    }, []);

    const closeSmartConnect = useCallback(() => {
        setSmartConnectMenu((prev) => ({ ...prev, isOpen: false }));
    }, []);

    /**
     * Find a compatible port on a node type for smart connect
     */
    const findCompatiblePortForSmartConnect = useCallback(
        (nodeType: NodeTypeDefinition, source: { nodeId: string; handleId: string; type: "source" | "target" }) => {
            if (source.type === "source") {
                // Dragging from output - find compatible input on new node
                const sourceType = getPortTypeForHandle(source.nodeId, source.handleId, "source");
                for (const port of nodeType.input_ports) {
                    const targetType = nodeType.input_port_types?.[port] || "any";
                    const resolvedTarget = typeof targetType === "string" ? { kind: targetType } : targetType;
                    // Skip non-control ports when source is control
                    if (sourceType.kind === "control" && resolvedTarget?.kind !== "control") {
                        continue;
                    }
                    if (arePortTypesCompatible(sourceType, targetType)) {
                        return { targetHandle: port, sourceType, targetType };
                    }
                }
                return null;
            }

            // Dragging from input - find compatible output on new node
            const targetType = getPortTypeForHandle(source.nodeId, source.handleId, "target");
            for (const port of nodeType.output_ports) {
                const sourceType = nodeType.output_port_types?.[port] || "any";
                const resolvedSource = typeof sourceType === "string" ? { kind: sourceType } : sourceType;
                // Skip non-control ports when target is control
                if (targetType.kind === "control" && resolvedSource?.kind !== "control") {
                    continue;
                }
                if (arePortTypesCompatible(sourceType, targetType)) {
                    return { sourceHandle: port, sourceType, targetType };
                }
            }
            return null;
        },
        [arePortTypesCompatible, getPortTypeForHandle]
    );

    /**
     * Filter node types to only those compatible with the current smart connect source
     */
    const getCompatibleNodeTypes = useCallback(
        (nodeLibrary: NodeTypeDefinition[]): NodeTypeDefinition[] => {
            if (!smartConnectMenu.source) return nodeLibrary;
            return nodeLibrary.filter((nodeType) =>
                Boolean(findCompatiblePortForSmartConnect(nodeType, smartConnectMenu.source!))
            );
        },
        [findCompatiblePortForSmartConnect, smartConnectMenu.source]
    );

    return {
        smartConnectMenu,
        setSmartConnectMenu,
        openSmartConnect,
        closeSmartConnect,
        findCompatiblePortForSmartConnect,
        getCompatibleNodeTypes,
    };
};
