import { useCallback, useMemo } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, TypeDescriptor } from "../types";
import { escapeId, formatPortTypeLabel, getPortTypeColor } from "../graph/utils";

interface ConnectionValidationResult {
    valid: boolean;
    reason?: string;
    sourceType?: TypeDescriptor;
    targetType?: TypeDescriptor;
}

interface UseConnectionValidationProps {
    nodes: Node<BlueprintNodeData>[];
    connectStartParams: {
        nodeId: string | null;
        handleId: string | null;
        handleType: "source" | "target" | null;
    } | null;
}

export const useConnectionValidation = ({
    nodes,
    connectStartParams,
}: UseConnectionValidationProps) => {
    const nodeMap = useMemo(
        () => new Map(nodes.map((node) => [node.id, node])),
        [nodes]
    );

    const normalizeType = useCallback(
        (type?: TypeDescriptor | string | null): TypeDescriptor => {
            if (!type) return { kind: "any" };
            if (typeof type === "string") {
                if (type === "number") return { kind: "float" };
                return { kind: type as TypeDescriptor["kind"] };
            }
            return type;
        },
        []
    );

    const arePortTypesCompatible = useCallback(
        (
            sourceType: TypeDescriptor | string | undefined,
            targetType: TypeDescriptor | string | undefined
        ): boolean => {
            const src = normalizeType(sourceType);
            const tgt = normalizeType(targetType);
            if (tgt.kind === "any" || src.kind === "any") return true;
            if (tgt.kind === "unknown" || src.kind === "unknown") return true;
            if (src.kind === "int" && tgt.kind === "float") return true;
            if (src.nullable && !tgt.nullable) return false;
            if (src.kind !== tgt.kind) return false;
            if (src.kind === "list" && src.item && tgt.item) {
                return arePortTypesCompatible(src.item, tgt.item);
            }
            if (src.kind === "map" && src.value && tgt.value) {
                return arePortTypesCompatible(src.value, tgt.value);
            }
            if (src.kind === "option" && src.item && tgt.item) {
                return arePortTypesCompatible(src.item, tgt.item);
            }
            if (src.kind === "record" && src.fields && tgt.fields) {
                const tgtKeys = Object.keys(tgt.fields);
                return tgtKeys.every(
                    (key) =>
                        src.fields &&
                        src.fields[key] &&
                        arePortTypesCompatible(src.fields[key], tgt.fields![key])
                );
            }
            if (src.kind === "tensor") {
                const srcDtype = src.metadata?.dtype;
                const tgtDtype = tgt.metadata?.dtype;
                if (srcDtype && tgtDtype && srcDtype !== tgtDtype) return false;
            }
            return true;
        },
        [normalizeType]
    );

    const getPortTypeForHandle = useCallback(
        (
            nodeId: string,
            handleId: string,
            role: "source" | "target"
        ): TypeDescriptor => {
            const node = nodeMap.get(nodeId);
            if (!node) return { kind: "any" };
            const map =
                role === "source"
                    ? node.data.output_port_types || node.data.metadata?.output_port_types
                    : node.data.input_port_types || node.data.metadata?.input_port_types;
            const value = map?.[handleId];
            if (!value) return { kind: "any" };
            if (typeof value === "string")
                return { kind: value as TypeDescriptor["kind"] };
            return value as TypeDescriptor;
        },
        [nodeMap]
    );

    const getHandleRoleFromDom = useCallback(
        (
            nodeId: string,
            handleId: string,
            side?: "source" | "target"
        ): "source" | "target" | null => {
            const safeNodeId = escapeId(nodeId);
            const safeHandleId = escapeId(handleId);
            const nodeSelector = `.react-flow__node[data-id="${safeNodeId}"]`;
            const baseSelector = `${nodeSelector} .react-flow__handle[data-handleid="${safeHandleId}"]`;
            const leftSelector = `${baseSelector}[data-handlepos="left"], ${nodeSelector} .react-flow__handle-target[data-handleid="${safeHandleId}"]`;
            const rightSelector = `${baseSelector}[data-handlepos="right"], ${nodeSelector} .react-flow__handle-source[data-handleid="${safeHandleId}"]`;
            const hasLeft = Boolean(document.querySelector(leftSelector));
            const hasRight = Boolean(document.querySelector(rightSelector));

            if (side === "target" && hasLeft) return "target";
            if (side === "source" && hasRight) return "source";
            if (hasLeft && !hasRight) return "target";
            if (hasRight && !hasLeft) return "source";
            return null;
        },
        []
    );

    const getHandleRole = useCallback(
        (
            nodeId: string,
            handleId: string,
            side?: "source" | "target"
        ): "source" | "target" | null => {
            const node = nodeMap.get(nodeId);
            if (!node) return null;
            if (
                side === "source" &&
                connectStartParams?.nodeId === nodeId &&
                connectStartParams.handleId === handleId &&
                connectStartParams.handleType
            ) {
                return connectStartParams.handleType;
            }
            const domRole = getHandleRoleFromDom(nodeId, handleId, side);
            if (domRole) return domRole;

            const isOutput = node.data.output_ports.includes(handleId);
            const isInput = node.data.input_ports.includes(handleId);
            if (isOutput && isInput && side) {
                return side;
            }
            if (isOutput) return "source";
            if (isInput) return "target";
            return null;
        },
        [connectStartParams, getHandleRoleFromDom, nodeMap]
    );

    const normalizeConnection = useCallback(
        (connection: {
            source: string | null;
            target: string | null;
            sourceHandle: string | null;
            targetHandle: string | null;
        }) => {
            if (
                !connection.source ||
                !connection.target ||
                !connection.sourceHandle ||
                !connection.targetHandle
            ) {
                return connection;
            }

            const sourceRole = getHandleRole(
                connection.source,
                connection.sourceHandle,
                "source"
            );
            const targetRole = getHandleRole(
                connection.target,
                connection.targetHandle,
                "target"
            );

            if (sourceRole === "target" && targetRole === "source") {
                return {
                    ...connection,
                    source: connection.target,
                    sourceHandle: connection.targetHandle,
                    target: connection.source,
                    targetHandle: connection.sourceHandle,
                };
            }

            return connection;
        },
        [getHandleRole]
    );

    const validateConnection = useCallback(
        (
            connection: {
                source: string | null;
                target: string | null;
                sourceHandle: string | null;
                targetHandle: string | null;
            },
            callbacks?: {
                setConnectionLineIsInvalid?: (invalid: boolean) => void;
                setConnectionLineColor?: (color: string | undefined) => void;
                setConnectionLineDash?: (dash: string | undefined) => void;
            }
        ): ConnectionValidationResult => {
            const { setConnectionLineIsInvalid, setConnectionLineColor, setConnectionLineDash } =
                callbacks || {};

            if (!connection.source || !connection.sourceHandle) {
                setConnectionLineIsInvalid?.(false);
                return { valid: false, reason: "Select both connectors" };
            }

            if (!connection.target || !connection.targetHandle) {
                const sourceRole = getHandleRole(
                    connection.source,
                    connection.sourceHandle,
                    "source"
                );
                const sourceType = getPortTypeForHandle(
                    connection.source,
                    connection.sourceHandle,
                    sourceRole === "target" ? "target" : "source"
                );
                setConnectionLineIsInvalid?.(false);
                setConnectionLineColor?.(getPortTypeColor(sourceType));
                setConnectionLineDash?.(sourceType.kind === "control" ? "8 4" : undefined);
                return { valid: true, sourceType };
            }

            const normalized = normalizeConnection(connection);
            const sourceRole = getHandleRole(
                normalized.source!,
                normalized.sourceHandle!,
                "source"
            );
            const targetRole = getHandleRole(
                normalized.target!,
                normalized.targetHandle!,
                "target"
            );

            if (sourceRole !== "source" || targetRole !== "target") {
                setConnectionLineIsInvalid?.(true);
                return { valid: false, reason: "Connect outputs to inputs only" };
            }

            if (normalized.source === normalized.target) {
                setConnectionLineIsInvalid?.(true);
                return { valid: false, reason: "Cannot connect a node to itself" };
            }

            const sourceType = getPortTypeForHandle(
                normalized.source!,
                normalized.sourceHandle!,
                "source"
            );
            const targetType = getPortTypeForHandle(
                normalized.target!,
                normalized.targetHandle!,
                "target"
            );
            const compatible = arePortTypesCompatible(sourceType, targetType);

            setConnectionLineIsInvalid?.(!compatible);
            const desiredColor = getPortTypeColor(sourceType);
            setConnectionLineDash?.(
                sourceType.kind === "control" || targetType.kind === "control"
                    ? "8 4"
                    : undefined
            );
            setConnectionLineColor?.(desiredColor);

            return {
                valid: compatible,
                reason: compatible
                    ? undefined
                    : `Type mismatch: ${formatPortTypeLabel(sourceType)} -> ${formatPortTypeLabel(targetType)}`,
                sourceType,
                targetType,
            };
        },
        [
            arePortTypesCompatible,
            getHandleRole,
            getPortTypeForHandle,
            normalizeConnection,
        ]
    );

    return {
        nodeMap,
        normalizeType,
        arePortTypesCompatible,
        getPortTypeForHandle,
        getHandleRole,
        getHandleRoleFromDom,
        normalizeConnection,
        validateConnection,
    };
};
