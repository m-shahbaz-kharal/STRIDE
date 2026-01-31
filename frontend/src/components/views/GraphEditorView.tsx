import React, { useCallback, useMemo } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Connection,
  MiniMap,
  Node,
  Edge,
  OnSelectionChangeParams,
  SelectionMode,
  ReactFlowInstance,
  NodeChange,
  EdgeChange,
} from "reactflow";
import "reactflow/dist/style.css";

import BlueprintNode from "../graph/BlueprintNode";
import CustomEdge from "../graph/CustomEdge";
import TypeAwareConnectionLine from "../graph/TypeAwareConnectionLine";
import ConnectionToast from "../ConnectionToast";
import { BlueprintNodeData, NodeTypeDefinition } from "../../types";
import { APP_HEADER_HEIGHT } from "../../graph/utils";

interface GraphEditorViewProps {
  visible: boolean;
  nodes: Node<BlueprintNodeData>[];
  edges: Edge[];
  onNodesChange: (changes: NodeChange[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onInit: (instance: ReactFlowInstance) => void;
  onNodeMouseEnter: (event: React.MouseEvent, node: Node) => void;
  onNodeMouseLeave: () => void;
  onConnect: (connection: Connection) => void;
  onConnectStart: (event: any, params: any) => void;
  onConnectEnd: (event: MouseEvent | TouchEvent) => void;
  onMoveStart: () => void;
  onNodeDragStart: () => void;
  onSelectionDragStart: () => void;
  onSelectionChange: (params: OnSelectionChangeParams) => void;
  isValidConnection: (connection: Connection) => boolean;
  connectionLineColor?: string;
  connectionLineIsInvalid: boolean;
  connectionLineDash?: string;
  connectionMessage: string | null;
  snapToGrid: boolean;
  setSnapToGrid: (value: boolean) => void;
  actualLeftWidth: number;
  actualRightWidth: number;
  canUndo: boolean;
  canRedo: boolean;
  undo: () => void;
  redo: () => void;
  minimapNodeColor: (node: Node<BlueprintNodeData>) => string;
  minimapNodeStroke: (node: Node<BlueprintNodeData>) => string;
  wrapperRef: React.RefObject<HTMLDivElement>;
  onMouseDown: (e: React.MouseEvent) => void;
  onMouseMove: (e: React.MouseEvent) => void;
  onMouseUp: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: (e: React.DragEvent) => void;
}

const GraphEditorView: React.FC<GraphEditorViewProps> = ({
  visible,
  nodes,
  edges,
  onNodesChange,
  onEdgesChange,
  onInit,
  onNodeMouseEnter,
  onNodeMouseLeave,
  onConnect,
  onConnectStart,
  onConnectEnd,
  onMoveStart,
  onNodeDragStart,
  onSelectionDragStart,
  onSelectionChange,
  isValidConnection,
  connectionLineColor,
  connectionLineIsInvalid,
  connectionLineDash,
  connectionMessage,
  snapToGrid,
  setSnapToGrid,
  actualLeftWidth,
  actualRightWidth,
  canUndo,
  canRedo,
  undo,
  redo,
  minimapNodeColor,
  minimapNodeStroke,
  wrapperRef,
  onMouseDown,
  onMouseMove,
  onMouseUp,
  onDragOver,
  onDrop,
}) => {
  const nodeTypes = useMemo(() => ({ blueprint: BlueprintNode }), []);
  const edgeTypes = useMemo(() => ({ default: CustomEdge }), []);

  return (
    <div
      className="reactflow-fullpage"
      ref={wrapperRef}
      onMouseDown={onMouseDown}
      onMouseMove={onMouseMove}
      onMouseUp={onMouseUp}
      onMouseLeave={onMouseUp}
      onDragOver={onDragOver}
      onDrop={onDrop}
      style={{ display: visible ? "block" : "none" }}
    >
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onInit={onInit}
        onNodeMouseEnter={onNodeMouseEnter}
        onNodeMouseLeave={onNodeMouseLeave}
        onConnect={onConnect}
        onConnectStart={onConnectStart}
        onConnectEnd={onConnectEnd}
        onMoveStart={onMoveStart}
        onNodeDragStart={onNodeDragStart}
        onSelectionDragStart={onSelectionDragStart}
        onSelectionChange={onSelectionChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        fitView
        minZoom={0.02}
        isValidConnection={isValidConnection}
        connectionLineStyle={{
          stroke: connectionLineColor || "#4a9eff",
          strokeWidth: connectionLineIsInvalid ? 3.2 : 2.5,
          strokeDasharray: connectionLineDash,
        }}
        connectionLineComponent={TypeAwareConnectionLine}
        attributionPosition="bottom-left"
        selectionMode={SelectionMode.Partial}
        selectionOnDrag
        panOnDrag={[1, 2]}
        selectNodesOnDrag
        edgesFocusable
        edgesUpdatable
        elementsSelectable
        snapToGrid={snapToGrid}
        snapGrid={[20, 20]}
      >
        {snapToGrid && <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="rgba(255,255,255,0.15)" />}
        <Controls
          showZoom
          showFitView
          showInteractive={false}
          position="bottom-left"
          style={{ left: actualLeftWidth }}
        />
        <MiniMap
          nodeColor={minimapNodeColor}
          nodeStrokeColor={minimapNodeStroke}
          nodeStrokeWidth={1}
          maskColor="rgba(0,0,0,0.65)"
          style={{
            backgroundColor: "rgba(20,25,35,0.9)",
            right: actualRightWidth,
          }}
          pannable
          zoomable
        />
      </ReactFlow>

      {/* Graph Editor Controls (Undo/Redo & Snap) */}
      <div style={{ position: 'absolute', top: APP_HEADER_HEIGHT + 20, right: actualRightWidth + 20, zIndex: 5, display: 'flex', gap: '10px', transition: 'right 0.3s ease' }}>
        {/* Undo/Redo */}
        <div style={{
          background: 'var(--bg-elevated)',
          padding: '4px',
          borderRadius: '8px',
          display: 'flex',
          gap: '4px',
          boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
          border: '1px solid var(--border-subtle)',
          alignItems: 'center',
          height: '36px',
          boxSizing: 'border-box'
        }}>
          <button
            onClick={undo}
            disabled={!canUndo}
            title="Undo (Ctrl+Z)"
            className="icon-btn"
            style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: !canUndo ? 0.3 : 1 }}>
              <path d="M3 7v6h6"></path>
              <path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"></path>
            </svg>
          </button>
          <button
            onClick={redo}
            disabled={!canRedo}
            title="Redo (Ctrl+Y)"
            className="icon-btn"
            style={{ width: 28, height: 28, border: 'none', background: 'transparent', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ opacity: !canRedo ? 0.3 : 1 }}>
              <path d="M21 7v6h-6"></path>
              <path d="M3 17a9 9 0 0 1 9-9 9 9 0 0 1 6 2.3L21 13"></path>
            </svg>
          </button>
        </div>

        {/* Snap Button */}
        <button
          onClick={() => setSnapToGrid(!snapToGrid)}
          title={`Snap to Grid: ${snapToGrid ? "On" : "Off"}`}
          style={{
            width: '36px',
            height: '36px',
            borderRadius: '8px',
            border: '1px solid var(--border-subtle)',
            background: snapToGrid ? 'var(--accent-primary)' : 'var(--bg-elevated)',
            color: snapToGrid ? 'white' : 'var(--text-secondary)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            transition: 'all 0.2s ease'
          }}
        >
          <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
            <path d="M10 10h4v4h-4zm0-6h4v4h-4zm0 12h4v4h-4zM4 4h4v4H4zm0 6h4v4H4zm0 6h4v4H4zM16 4h4v4h-4zm0 6h4v4h-4zm0 6h4v4h-4z" />
          </svg>
        </button>
      </div>

      <ConnectionToast message={connectionMessage} />
    </div>
  );
};

export default GraphEditorView;
