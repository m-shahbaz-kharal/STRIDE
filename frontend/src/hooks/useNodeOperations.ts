import { useCallback, useRef } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, NodeTypeDefinition, TypeDescriptor } from "../types";
import { computeNodeDimensions, HEADER_HEIGHT, PORT_ROW_HEIGHT } from "../graph/utils";

interface CreateNodeOptions {
    position: { x: number; y: number };
    nodeType: NodeTypeDefinition;
    handlers: NodeHandlers;
}

interface NodeHandlers {
    onDelete?: (nodeId: string) => void;
    onRunSelection?: (nodeId: string) => void;
    onClearCache?: (nodeId: string) => void;
    onInterrupt?: (nodeId: string) => void;
    onParamChange?: (nodeId: string, param: string, value: string | number | boolean | null) => void;
    onPortHover?: (info: { nodeId: string; port: string; direction: "input" | "output" } | null) => void;
    onInputValueChange?: (nodeId: string, port: string, value: string | number | boolean | null) => void;
    onAddInputPort?: (nodeId: string) => void;
    onToggleCache?: (nodeId: string) => void;
}

interface UseNodeOperationsOptions {
    setNodes: React.Dispatch<React.SetStateAction<Node<BlueprintNodeData>[]>>;
    setEdges: React.Dispatch<React.SetStateAction<any[]>>;
    takeSnapshot: () => void;
    dashboardLayout: { widgets: { id: string; nodeId?: string; portName?: string }[] };
    setDashboardLayout: (layout: any) => void;
    onShowWarning: (message: string, onConfirm: () => void) => void;
    nodes: Node<BlueprintNodeData>[];
}

export const useNodeOperations = ({
    setNodes,
    setEdges,
    takeSnapshot,
    dashboardLayout,
    setDashboardLayout,
    onShowWarning,
    nodes,
}: UseNodeOperationsOptions) => {
    const nodeIdRef = useRef(1);

    const buildDefaultInputValues = useCallback((nodeType: NodeTypeDefinition) => {
        const inputValues: Record<string, unknown> = {};
        for (const input of nodeType.inputs ?? []) {
            if (input.type?.kind === "control") {
                continue;
            }
            if (input.default !== undefined && input.default !== null) {
                inputValues[input.name] = input.default;
            }
        }
        return inputValues;
    }, []);

    const getInitialPorts = useCallback((nodeType: NodeTypeDefinition) => {
        if (nodeType.node_type === "core.container.make_array") {
            return {
                input_ports: ["control_in", "item_0"],
                input_port_types: { control_in: { kind: "control" }, item_0: { kind: "any" } } as Record<string, TypeDescriptor>,
            };
        }
        return {
            input_ports: nodeType.input_ports,
            input_port_types: nodeType.input_port_types as Record<string, TypeDescriptor>,
        };
    }, []);

    /**
     * Creates a new node from a node type definition.
     * This is the shared node creation utility used by:
     * - handleAddNode (palette click)
     * - handleSmartConnectSelect (smart connect)
     * - handleDrop (drag & drop)
     */
    const createNodeFromType = useCallback((
        nodeType: NodeTypeDefinition,
        position: { x: number; y: number },
        handlers: NodeHandlers
    ): Node<BlueprintNodeData> => {
        const params: Record<string, unknown> = {};
        const defaults = nodeType.params_defaults ?? {};
        for (const [key, schema] of Object.entries(nodeType.params_schema ?? {})) {
            params[key] = schema.default ?? defaults[key] ?? "";
        }

        const { input_ports, input_port_types } = getInitialPorts(nodeType);
        const inputValues = buildDefaultInputValues(nodeType);
        const seededInputValues =
            nodeType.node_type === "core.container.make_array"
                ? { ...inputValues, item_0: null }
                : inputValues;

        const id = `node-${nodeIdRef.current++}`;

        // Calculate initial size based on ports
        const extraInputRows = nodeType.node_type === "core.container.make_array" ? 1 : 0;
        const maxPorts = Math.max(input_ports.length + extraInputRows, nodeType.output_ports.length);
        const paramCount = Object.keys(nodeType.params_schema ?? {}).length;
        const { width: initialWidth, height: initialHeight } = computeNodeDimensions(maxPorts, { paramCount });

        return {
            id,
            type: "blueprint",
            position,
            data: {
                displayName: nodeType.display_name,
                nodeType: nodeType.node_type,
                description: nodeType.description,
                input_ports,
                output_ports: nodeType.output_ports,
                input_port_types,
                output_port_types: nodeType.output_port_types,
                params,
                inputValues: seededInputValues,
                breakpoint: false,
                cacheEnabled: false,
                metadata: nodeType,
                width: initialWidth,
                height: initialHeight,
                executionLogs: [],
                ...handlers,
            },
        };
    }, [buildDefaultInputValues, getInitialPorts]);

    const handleAddNode = useCallback(
        (nodeType: NodeTypeDefinition, handlers: NodeHandlers, nodesLength: number) => {
            takeSnapshot();
            const position = { x: 120 + nodesLength * 36, y: 80 + nodesLength * 32 };
            const newNode = createNodeFromType(nodeType, position, handlers);
            setNodes((existing) => existing.concat(newNode));
            return newNode.id;
        },
        [createNodeFromType, setNodes, takeSnapshot]
    );

    const updateNodeData = useCallback(
        (nodeId: string, updater: (data: BlueprintNodeData) => BlueprintNodeData) => {
            setNodes((nd) =>
                nd.map((node) => (node.id === nodeId ? { ...node, data: updater(node.data) } : node))
            );
        },
        [setNodes]
    );

    const handleParamChange = useCallback(
        (nodeId: string, param: string, value: string | number | boolean | null) =>
            updateNodeData(nodeId, (data) => ({
                ...data,
                params: { ...data.params, [param]: value },
            })),
        [updateNodeData]
    );

    const handleInputValueChange = useCallback(
        (nodeId: string, port: string, value: string | number | boolean | null) =>
            updateNodeData(nodeId, (data) => ({
                ...data,
                inputValues: { ...(data.inputValues ?? {}), [port]: value },
            })),
        [updateNodeData]
    );

    const handleTogglePublish = useCallback(
        (nodeId: string, portId: string, direction: "input" | "output", kind: any) => {
            const performToggle = () => {
                updateNodeData(nodeId, (data) => {
                    const published = { ...(data.published_ports ?? {}) };
                    const key = `${direction}_${portId}`;

                    if (published[key]) {
                        delete published[key];
                    } else {
                        published[key] = {
                            alias: `${data.displayName} - ${portId}`,
                            portId,
                            kind: kind?.kind || "any",
                            direction
                        };
                    }

                    return { ...data, published_ports: published };
                });
            };

            // Check if unpublishing
            const node = nodes.find(n => n.id === nodeId);
            const key = `${direction}_${portId}`;
            const isUnpublishing = node?.data.published_ports?.[key];

            if (isUnpublishing) {
                // Check for dependent widgets
                // Note: The widget binding uses "portName" which corresponds to "portId" in "published_ports"
                const dependentWidgets = dashboardLayout.widgets.filter(
                    w => w.nodeId === nodeId && w.portName === portId
                );

                if (dependentWidgets.length > 0) {
                    onShowWarning(
                        `Unpublishing this port will remove ${dependentWidgets.length} dependent UI element(s) from the dashboard. Proceed?`,
                        () => {
                            // Remove widgets
                            setDashboardLayout((prev: any) => ({
                                ...prev,
                                widgets: prev.widgets.filter((w: any) => !(w.nodeId === nodeId && w.portName === portId))
                            }));
                            performToggle();
                        }
                    );
                    return;
                }
            }

            performToggle();
        },
        [updateNodeData, nodes, dashboardLayout, onShowWarning, setDashboardLayout]
    );

    const handleAddInputPort = useCallback(
        (nodeId: string) =>
            updateNodeData(nodeId, (data) => {
                const existing = data.input_ports.filter((port) => port.startsWith("item_"));
                const nextIndex = existing.length > 0
                    ? Math.max(...existing.map((port) => Number(port.split("_")[1]) || 0)) + 1
                    : 0;
                const nextPort = `item_${nextIndex}`;
                const input_ports = [...data.input_ports, nextPort];
                const input_port_types = { ...(data.input_port_types ?? {}), [nextPort]: { kind: "any" as const } };
                const inputValues = { ...(data.inputValues ?? {}), [nextPort]: null };
                const extraInputRows = data.nodeType === "core.container.make_array" ? 1 : 0;
                const maxPorts = Math.max(input_ports.length + extraInputRows, data.output_ports.length);
                const paramCount = Object.keys(data.metadata?.params_schema ?? {}).length;
                const { width, height } = computeNodeDimensions(maxPorts, { paramCount });
                return {
                    ...data,
                    input_ports,
                    input_port_types,
                    inputValues,
                    width,
                    height,
                };
            }),
        [updateNodeData]
    );

    const handleDeleteNode = useCallback((nodeId: string) => {
        const performDelete = () => {
            setNodes((current) => current.filter((node) => node.id !== nodeId));
            setEdges((current) =>
                current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId)
            );
        };

        const dependentWidgets = dashboardLayout.widgets.filter(w => w.nodeId === nodeId);

        if (dependentWidgets.length > 0) {
            onShowWarning(
                `Deleting this node will remove ${dependentWidgets.length} dependent UI element(s) from the dashboard. Proceed?`,
                () => {
                    setDashboardLayout((prev: any) => ({
                        ...prev,
                        widgets: prev.widgets.filter((w: any) => w.nodeId !== nodeId)
                    }));
                    performDelete();
                }
            );
        } else {
            performDelete();
        }
    }, [setEdges, setNodes, dashboardLayout, onShowWarning, setDashboardLayout]);

    const clearNodeCache = useCallback((nodeId: string) => {
        setNodes((existing) =>
            existing.map((n) =>
                n.id === nodeId
                    ? {
                        ...n,
                        data: {
                            ...n.data,
                            last_outputs: undefined,
                            executionStatus: undefined,
                            executionDuration: undefined,
                            executionLogs: [],
                        },
                    }
                    : n
            )
        );
    }, [setNodes]);

    const clearAllCache = useCallback(() => {
        setNodes((existing) =>
            existing.map((node) => ({
                ...node,
                data: {
                    ...node.data,
                    last_outputs: undefined,
                    executionStatus: undefined,
                    executionDuration: undefined,
                    executionLogs: [],
                },
            }))
        );
    }, [setNodes]);

    /**
     * Returns the vertical Y offset for a port in a node
     */
    const getPortYOffset = useCallback((portIndex: number): number => {
        return HEADER_HEIGHT + portIndex * PORT_ROW_HEIGHT + PORT_ROW_HEIGHT / 2;
    }, []);

    return {
        nodeIdRef,
        createNodeFromType,
        handleAddNode,
        updateNodeData,
        handleParamChange,
        handleInputValueChange,
        handleAddInputPort,
        handleDeleteNode,
        clearNodeCache,
        clearAllCache,
        buildDefaultInputValues,
        getInitialPorts,
        getPortYOffset,
        handleTogglePublish,
    };
};
