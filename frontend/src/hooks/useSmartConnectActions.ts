/**
 * Smart connect actions hook.
 *
 * Handles the smart connect feature that allows users to create
 * new nodes by dragging from an existing port. This is extracted
 * from App.tsx to reduce its size.
 */

import { useCallback } from 'react';
import { Node, Edge, addEdge } from 'reactflow';
import { BlueprintNodeData, NodeTypeDefinition, TypeDescriptor } from '../types';
import { computeNodeDimensions, getPortTypeColor } from '../graph/utils';

interface SmartConnectSource {
  nodeId: string;
  handleId: string;
  type: 'source' | 'target';
}

interface SmartConnectMenu {
  isOpen: boolean;
  position: { x: number; y: number };
  flowPosition: { x: number; y: number };
  source: SmartConnectSource | null;
  sourcePortKind: TypeDescriptor | null;
}

interface CompatiblePort {
  sourceHandle?: string;
  targetHandle?: string;
  sourceType?: TypeDescriptor;
  targetType?: TypeDescriptor;
}

interface UseSmartConnectActionsProps {
  smartConnectMenu: SmartConnectMenu;
  setNodes: (nodes: Node<BlueprintNodeData>[] | ((nds: Node<BlueprintNodeData>[]) => Node<BlueprintNodeData>[])) => void;
  setEdges: (edges: Edge[] | ((eds: Edge[]) => Edge[])) => void;
  createNodeFromType: (
    nodeType: NodeTypeDefinition,
    position: { x: number; y: number },
    handlers?: any
  ) => Node<BlueprintNodeData>;
  nodeHandlers: any;
  arePortTypesCompatible: (sourceType: TypeDescriptor | string | undefined, targetType: TypeDescriptor | string | undefined) => boolean;
  findCompatiblePortForSmartConnect: (nodeType: NodeTypeDefinition, source: SmartConnectSource) => CompatiblePort | null;
  closeSmartConnect: () => void;
  showConnectionMessage: (message: string) => void;
  takeSnapshot: () => void;
  getPortYOffset: (portIndex: number) => number;
}

export const useSmartConnectActions = ({
  smartConnectMenu,
  setNodes,
  setEdges,
  createNodeFromType,
  nodeHandlers,
  arePortTypesCompatible,
  findCompatiblePortForSmartConnect,
  closeSmartConnect,
  showConnectionMessage,
  takeSnapshot,
  getPortYOffset,
}: UseSmartConnectActionsProps) => {
  /**
   * Handle selection of a node type from the smart connect menu.
   */
  const handleSmartConnectSelect = useCallback(
    (nodeType: NodeTypeDefinition) => {
      if (!smartConnectMenu.source) return;

      takeSnapshot();

      const { flowPosition, source } = smartConnectMenu;
      const compatiblePort = findCompatiblePortForSmartConnect(nodeType, source);
      if (!compatiblePort) {
        showConnectionMessage('No compatible ports found for this node');
        closeSmartConnect();
        return;
      }

      // Calculate position to align the connecting handle
      const { input_ports } = nodeType.node_type === 'core.container.make_array'
        ? { input_ports: ['control_in', 'item_0'] }
        : { input_ports: nodeType.input_ports };

      const matchedPortIndex = source.type === 'source'
        ? input_ports.indexOf(compatiblePort.targetHandle!)
        : nodeType.output_ports.indexOf(compatiblePort.sourceHandle!);
      const resolvedPortIndex = matchedPortIndex >= 0 ? matchedPortIndex : 0;
      const portYOffset = getPortYOffset(resolvedPortIndex);

      const extraInputRows = nodeType.node_type === 'core.container.make_array' ? 1 : 0;
      const maxPorts = Math.max(input_ports.length + extraInputRows, nodeType.output_ports.length);
      const paramCount = Object.keys(nodeType.params_schema ?? {}).length;
      const { width: initialWidth } = computeNodeDimensions(maxPorts, { paramCount });

      let xOffset = 0;
      if (source.type === 'source') {
        xOffset = 0;
      } else {
        xOffset = initialWidth;
      }

      const newNode = createNodeFromType(
        nodeType,
        { x: flowPosition.x - xOffset, y: flowPosition.y - portYOffset },
        nodeHandlers
      );

      const isControlConnection =
        (typeof compatiblePort.sourceType === 'object' && compatiblePort.sourceType?.kind === 'control') ||
        (typeof compatiblePort.targetType === 'object' && compatiblePort.targetType?.kind === 'control');
      const hydratedNewNode = isControlConnection
        ? { ...newNode, data: { ...newNode.data, showControlPorts: true } }
        : newNode;

      setNodes((nds) => nds.concat(hydratedNewNode));

      // Create connection
      let sourceId: string;
      let sourceHandle: string | undefined;
      let targetId: string;
      let targetHandle: string | undefined;

      if (source.type === 'source') {
        sourceId = source.nodeId;
        sourceHandle = source.handleId;
        targetId = newNode.id;
        targetHandle = compatiblePort.targetHandle;
      } else {
        sourceId = newNode.id;
        sourceHandle = compatiblePort.sourceHandle;
        targetId = source.nodeId;
        targetHandle = source.handleId;
      }

      if (sourceHandle && targetHandle) {
        const sourceType = compatiblePort.sourceType;
        const targetType = compatiblePort.targetType;

        if (arePortTypesCompatible(sourceType, targetType)) {
          const edgeColor = getPortTypeColor(sourceType);
          setEdges((eds) => {
            const filtered = source.type === 'target'
              ? eds.filter((edge) => !(edge.target === targetId && edge.targetHandle === targetHandle))
              : eds;
            return addEdge(
              {
                source: sourceId,
                sourceHandle: sourceHandle,
                target: targetId,
                targetHandle: targetHandle,
                type: 'default',
                animated: false,
                style: { stroke: edgeColor, strokeWidth: 2 },
                data: { kind: isControlConnection ? 'control' : 'data' },
              },
              filtered
            );
          });
        }
      }

      closeSmartConnect();
    },
    [
      smartConnectMenu,
      createNodeFromType,
      nodeHandlers,
      setNodes,
      setEdges,
      arePortTypesCompatible,
      findCompatiblePortForSmartConnect,
      closeSmartConnect,
      showConnectionMessage,
      takeSnapshot,
      getPortYOffset,
    ]
  );

  return {
    handleSmartConnectSelect,
  };
};
