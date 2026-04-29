import { useCallback, useMemo } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, TypeDescriptor } from "../types";
import { escapeId, formatPortTypeLabel, getPortTypeColor } from "../graph/utils";

interface ConnectionValidationResult {
    valid: boolean;
    reason?: string;
    sourceType?: TypeDescriptor;
    targetType?: TypeDescriptor;
    classification?: PortCompatibility;
}

// Phase 3 §7.1: per-target classification used to drive port highlighting
// while a connection is in progress.
//
// - "compatible":   directly assignable per `arePortTypesCompatible`.
// - "convertible":  same kind but the target wants a narrower subtype than
//                   the source advertises (e.g. source `image[any]` →
//                   target `image[rgb]`). Once `stride-converters` lands
//                   (Phase 5) this also covers cross-kind paths reachable
//                   through a registered converter.
// - "incompatible": no path; rendering should grey the port out.
// - "neutral":      not part of the current drag (self-port, wrong
//                   direction, no active drag).
export type PortCompatibility =
    | "compatible"
    | "convertible"
    | "incompatible"
    | "neutral";

export interface ClassifyOptions {
    // The handle the user grabbed (`source` = an output, `target` = an input).
    sourceRole: "source" | "target";
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
            const normalized: TypeDescriptor & Record<string, unknown> = { ...type } as TypeDescriptor;
            const elementType = (normalized as any).elementType ?? (normalized as any).element_type;
            const normalizedElement = elementType ? normalizeType(elementType) : undefined;
            if (normalized.kind === "map") {
                if (normalizedElement && !normalized.value) {
                    normalized.value = normalizedElement;
                }
                if (!normalized.value && normalized.item) {
                    normalized.value = normalized.item;
                }
            } else if (normalizedElement && !normalized.item) {
                normalized.item = normalizedElement;
            }
            if (normalized.item && typeof normalized.item === "object") {
                normalized.item = normalizeType(normalized.item);
            }
            if (normalized.value && typeof normalized.value === "object") {
                normalized.value = normalizeType(normalized.value);
            }
            if (normalized.fields) {
                normalized.fields = Object.fromEntries(
                    Object.entries(normalized.fields).map(([key, value]) => [key, normalizeType(value)])
                );
            }
            return normalized;
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

    // Phase 3 §7.1: classify how a *target* port relates to a *source*
    // port, *given* both are direction-correct (output → input). We treat
    // anything that `arePortTypesCompatible` accepts as "compatible". The
    // narrower bucket "convertible" is reserved for same-kind pairs whose
    // subtype metadata cannot be unified — i.e. the connection would need
    // an explicit conversion node before it becomes valid.
    //
    // Cross-kind pairs are "incompatible" until `stride-converters` ships
    // a converter index in Phase 5. At that point this function will also
    // consult the converter registry; see TODO at end of file.
    const classifyAssignment = useCallback(
        (
            sourceType: TypeDescriptor | string | undefined,
            targetType: TypeDescriptor | string | undefined
        ): PortCompatibility => {
            if (arePortTypesCompatible(sourceType, targetType)) {
                return "compatible";
            }
            const src = normalizeType(sourceType);
            const tgt = normalizeType(targetType);

            // Same-kind narrowing: source advertises a wider subtype
            // (or no subtype) than the target requires. A converter
            // could plausibly resolve this — the user will be prompted.
            if (src.kind === tgt.kind) {
                const srcSubtype = (src.metadata?.subtype as string | undefined) ?? null;
                const tgtSubtype = (tgt.metadata?.subtype as string | undefined) ?? null;
                if (tgtSubtype && srcSubtype !== tgtSubtype) {
                    return "convertible";
                }
                // List/map element-type narrowing — recurse into the item type.
                if (src.kind === "list" && src.item && tgt.item) {
                    const inner = classifyAssignment(src.item, tgt.item);
                    if (inner === "convertible") return "convertible";
                }
                if (src.kind === "map" && src.value && tgt.value) {
                    const inner = classifyAssignment(src.value, tgt.value);
                    if (inner === "convertible") return "convertible";
                }
            }

            return "incompatible";
        },
        [arePortTypesCompatible, normalizeType]
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

            const classification = compatible
                ? "compatible"
                : classifyAssignment(sourceType, targetType);

            return {
                valid: compatible,
                reason: compatible
                    ? undefined
                    : `Type mismatch: ${formatPortTypeLabel(sourceType)} -> ${formatPortTypeLabel(targetType)}`,
                sourceType,
                targetType,
                classification,
            };
        },
        [
            arePortTypesCompatible,
            classifyAssignment,
            getHandleRole,
            getPortTypeForHandle,
            normalizeConnection,
        ]
    );

    // Phase 3 §7.1: classify a single (otherCandidate) port relative to
    // the currently dragged port. Used by BlueprintNode to decorate every
    // input port on every other node during a drag.
    //
    // Returns `"neutral"` when:
    //   - no drag is active
    //   - the candidate is on the same node as the drag origin
    //   - the candidate has the wrong direction for this drag (e.g. user
    //     is dragging from an output, candidate is also an output)
    const classifyPortForDrag = useCallback(
        (
            candidateNodeId: string,
            candidateHandleId: string,
            candidateDirection: "input" | "output"
        ): PortCompatibility => {
            if (!connectStartParams?.nodeId || !connectStartParams.handleId || !connectStartParams.handleType) {
                return "neutral";
            }
            // Can't connect a port to itself or anywhere else on the same node.
            if (candidateNodeId === connectStartParams.nodeId) {
                return "neutral";
            }
            // Direction must be the opposite of what the user grabbed.
            const dragRole = connectStartParams.handleType;
            const wantedDirection = dragRole === "source" ? "input" : "output";
            if (candidateDirection !== wantedDirection) {
                return "neutral";
            }

            const dragType = getPortTypeForHandle(
                connectStartParams.nodeId,
                connectStartParams.handleId,
                dragRole
            );
            const candidateType = getPortTypeForHandle(
                candidateNodeId,
                candidateHandleId,
                candidateDirection === "input" ? "target" : "source"
            );

            // Resolve who is the source and who is the target type-wise
            // (independent of which side the user grabbed).
            const [sourceType, targetType] = dragRole === "source"
                ? [dragType, candidateType]
                : [candidateType, dragType];

            return classifyAssignment(sourceType, targetType);
        },
        [classifyAssignment, connectStartParams, getPortTypeForHandle]
    );

    // Re-validate every existing edge against current node port types.
    // Phase 3 §7.3: nodes whose params change can mutate their declared
    // port types; edges that pointed at them need a refresh. Returns a
    // map of edgeId → classification for any edge that is no longer
    // strictly compatible. Unchanged edges are omitted from the map so
    // callers can clear bad-edge state with `.size === 0`.
    const revalidateEdges = useCallback(
        (
            edges: Array<{
                id: string;
                source: string;
                sourceHandle?: string | null;
                target: string;
                targetHandle?: string | null;
                data?: { kind?: "data" | "control" } | undefined;
            }>
        ): Map<string, { classification: PortCompatibility; reason: string }> => {
            const result = new Map<string, { classification: PortCompatibility; reason: string }>();
            for (const edge of edges) {
                if (!edge.sourceHandle || !edge.targetHandle) continue;
                // Skip control edges — kind matches by construction.
                if (edge.data?.kind === "control") continue;
                const sourceType = getPortTypeForHandle(edge.source, edge.sourceHandle, "source");
                const targetType = getPortTypeForHandle(edge.target, edge.targetHandle, "target");
                if (arePortTypesCompatible(sourceType, targetType)) continue;
                const classification = classifyAssignment(sourceType, targetType);
                result.set(edge.id, {
                    classification,
                    reason: `${formatPortTypeLabel(sourceType)} → ${formatPortTypeLabel(targetType)} no longer compatible`,
                });
            }
            return result;
        },
        [arePortTypesCompatible, classifyAssignment, getPortTypeForHandle]
    );

    return {
        nodeMap,
        normalizeType,
        arePortTypesCompatible,
        classifyAssignment,
        classifyPortForDrag,
        revalidateEdges,
        getPortTypeForHandle,
        getHandleRole,
        getHandleRoleFromDom,
        normalizeConnection,
        validateConnection,
    };
};

// Phase 3 §7.1: re-export pure classifier helpers so non-hook code
// (visualisers, vitest unit tests) can call them without spinning up a
// React tree. The hook already wraps these in `useCallback`; the bare
// functions below have no React dependencies.
export const classifyAssignmentPure = (
    sourceType: TypeDescriptor | string | undefined,
    targetType: TypeDescriptor | string | undefined,
    isAssignable: (
        a: TypeDescriptor | string | undefined,
        b: TypeDescriptor | string | undefined
    ) => boolean
): PortCompatibility => {
    if (isAssignable(sourceType, targetType)) return "compatible";

    const norm = (t?: TypeDescriptor | string): TypeDescriptor => {
        if (!t) return { kind: "any" };
        if (typeof t === "string") return { kind: t as TypeDescriptor["kind"] };
        return t;
    };
    const src = norm(sourceType);
    const tgt = norm(targetType);
    if (src.kind === tgt.kind) {
        const srcSubtype = (src.metadata?.subtype as string | undefined) ?? null;
        const tgtSubtype = (tgt.metadata?.subtype as string | undefined) ?? null;
        if (tgtSubtype && srcSubtype !== tgtSubtype) return "convertible";
    }
    return "incompatible";
};

// TODO(Phase 5 / stride-converters): once the converter index is built,
// `classifyAssignment` should also return "convertible" for cross-kind
// pairs that have a registered converter, and "compatible" for free
// (zero-cost) implicit conversions per §4.2 of the design doc.
