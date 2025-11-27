import React from "react";
import { NodeTypeDefinition } from "../types";

type NodePaletteProps = {
  nodeTypes: NodeTypeDefinition[];
  onAddNode: (nodeType: NodeTypeDefinition) => void;
};

const NodePalette = ({ nodeTypes, onAddNode }: NodePaletteProps) => (
  <div className="panel palette-panel">
    <div className="panel-header">
      <div>
        <h3>Node Library</h3>
        <p>Pick a registered node and drop it into your canvas.</p>
      </div>
    </div>
    <div className="palette-list">
      {nodeTypes.map((nodeType) => (
        <button
          key={nodeType.node_type}
          type="button"
          className="palette-card"
          onClick={() => onAddNode(nodeType)}
        >
          <div className="palette-card-meta">
            <strong>{nodeType.display_name}</strong>
            <span className="palette-node-type">{nodeType.node_type}</span>
            <p>{nodeType.description}</p>
          </div>
          <span className="palette-action">+ Add</span>
        </button>
      ))}
      {nodeTypes.length === 0 && (
        <p className="palette-empty">Loading node registry from backend...</p>
      )}
    </div>
  </div>
);

export default NodePalette;

