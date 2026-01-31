import { useCallback, useState, useRef } from "react";
import { Node, Edge, ReactFlowInstance } from "reactflow";
import { BlueprintNodeData } from "../types";
import { MIN_NODE_WIDTH, bezierIntersectsRect, computeNodeDimensions } from "../graph/utils";

interface UseEdgeSelectionOptions {
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  setEdges: (edges: Edge[] | ((eds: Edge[]) => Edge[])) => void;
  setSelectedEdgeIds: (ids: string[] | ((prev: string[]) => string[])) => void;
  reactFlowWrapper: React.RefObject<HTMLDivElement>;
}

export const useEdgeSelection = ({
  nodes,
  edges,
  setEdges,
  setSelectedEdgeIds,
  reactFlowWrapper,
}: UseEdgeSelectionOptions) => {
  const [isSelecting, setIsSelecting] = useState(false);
  const [selectionBox, setSelectionBox] = useState<{ startX: number; startY: number; endX: number; endY: number } | null>(null);
  const [previewEdgeIds, setPreviewEdgeIds] = useState<string[]>([]);

  const getViewport = useCallback(() => {
    const wrapper = reactFlowWrapper.current;
    if (wrapper) {
      const rfInstance = wrapper.querySelector('.react-flow__viewport');
      if (rfInstance) {
        const transform = rfInstance.getAttribute('style');
        const match = transform?.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)\s*scale\(([\d.]+)\)/);
        if (match) {
          return {
            x: parseFloat(match[1]),
            y: parseFloat(match[2]),
            zoom: parseFloat(match[3]),
          };
        }
      }
    }
    return { x: 0, y: 0, zoom: 1 };
  }, [reactFlowWrapper]);

  const findIntersectingEdges = useCallback((
    box: { startX: number; startY: number; endX: number; endY: number },
    viewport: { x: number; y: number; zoom: number }
  ): string[] => {
    const toFlowCoord = (screenX: number, screenY: number) => ({
      x: (screenX - viewport.x) / viewport.zoom,
      y: (screenY - viewport.y) / viewport.zoom,
    });

    const start = toFlowCoord(box.startX, box.startY);
    const end = toFlowCoord(box.endX, box.endY);

    const rx = Math.min(start.x, end.x);
    const ry = Math.min(start.y, end.y);
    const rw = Math.abs(end.x - start.x);
    const rh = Math.abs(end.y - start.y);

    if (rw < 5 && rh < 5) return [];

    const intersectingEdgeIds: string[] = [];

    edges.forEach((edge) => {
      const sourceNode = nodes.find((n) => n.id === edge.source);
      const targetNode = nodes.find((n) => n.id === edge.target);

      if (!sourceNode || !targetNode) return;

      const sourceX = sourceNode.position.x + (sourceNode.width || MIN_NODE_WIDTH);
      const sourceParamCount = Object.keys(sourceNode.data.metadata?.params_schema ?? {}).length;
      const sourceMaxPorts = Math.max(sourceNode.data.input_ports.length, sourceNode.data.output_ports.length);
      const sourceFallbackHeight = computeNodeDimensions(sourceMaxPorts, { paramCount: sourceParamCount }).height;
      const sourceY = sourceNode.position.y + (sourceNode.height || sourceFallbackHeight) / 2;
      const targetX = targetNode.position.x;
      const targetParamCount = Object.keys(targetNode.data.metadata?.params_schema ?? {}).length;
      const targetMaxPorts = Math.max(targetNode.data.input_ports.length, targetNode.data.output_ports.length);
      const targetFallbackHeight = computeNodeDimensions(targetMaxPorts, { paramCount: targetParamCount }).height;
      const targetY = targetNode.position.y + (targetNode.height || targetFallbackHeight) / 2;

      if (bezierIntersectsRect(sourceX, sourceY, targetX, targetY, rx, ry, rw, rh)) {
        intersectingEdgeIds.push(edge.id);
      }
    });

    return intersectingEdgeIds;
  }, [edges, nodes]);

  const updatePreviewEdges = useCallback((box: { startX: number; startY: number; endX: number; endY: number }) => {
    const viewport = getViewport();
    const intersectingEdges = findIntersectingEdges(box, viewport);
    setPreviewEdgeIds(intersectingEdges);
  }, [getViewport, findIntersectingEdges]);

  const handleSelectionEnd = useCallback(() => {
    if (previewEdgeIds.length > 0) {
      setSelectedEdgeIds((prev) => {
        const combined = new Set([...prev, ...previewEdgeIds]);
        return Array.from(combined);
      });
      setEdges((eds) =>
        eds.map((e) => ({
          ...e,
          selected: previewEdgeIds.includes(e.id) || e.selected,
        }))
      );
    }
    setSelectionBox(null);
    setPreviewEdgeIds([]);
    setIsSelecting(false);
  }, [previewEdgeIds, setEdges, setSelectedEdgeIds]);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button === 0 && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      const target = e.target;
      if (target instanceof HTMLElement && target.classList.contains('react-flow__pane')) {
        const rect = reactFlowWrapper.current?.getBoundingClientRect();
        if (rect) {
          setIsSelecting(true);
          setSelectionBox({
            startX: e.clientX - rect.left,
            startY: e.clientY - rect.top,
            endX: e.clientX - rect.left,
            endY: e.clientY - rect.top,
          });
        }
      }
    }
  }, [reactFlowWrapper]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (isSelecting && selectionBox) {
      const rect = reactFlowWrapper.current?.getBoundingClientRect();
      if (rect) {
        const newBox = {
          ...selectionBox,
          endX: e.clientX - rect.left,
          endY: e.clientY - rect.top,
        };
        setSelectionBox(newBox);
        updatePreviewEdges(newBox);
      }
    }
  }, [isSelecting, selectionBox, reactFlowWrapper, updatePreviewEdges]);

  const handleMouseUp = useCallback(() => {
    if (isSelecting) {
      handleSelectionEnd();
    }
  }, [isSelecting, handleSelectionEnd]);

  return {
    isSelecting,
    setIsSelecting,
    selectionBox,
    setSelectionBox,
    previewEdgeIds,
    setPreviewEdgeIds,
    getViewport,
    findIntersectingEdges,
    updatePreviewEdges,
    handleSelectionEnd,
    handleMouseDown,
    handleMouseMove,
    handleMouseUp,
  };
};
