import React, { useMemo, useState } from "react";
import { NodeTypeDefinition } from "../types";

type NodePaletteProps = {
  nodeTypes: NodeTypeDefinition[];
  onAddNode: (nodeType: NodeTypeDefinition) => void;
};

const NodePalette = ({ nodeTypes, onAddNode }: NodePaletteProps) => {
  const [query, setQuery] = useState("");

  const filteredNodeTypes = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    if (!normalizedQuery) {
      return nodeTypes;
    }
    return nodeTypes.filter((nodeType) => {
      const searchableValue = `${nodeType.display_name} ${nodeType.node_type} ${nodeType.description}`.toLowerCase();
      return searchableValue.includes(normalizedQuery);
    });
  }, [nodeTypes, query]);

  const isLoading = nodeTypes.length === 0;
  const showNoMatches = !isLoading && filteredNodeTypes.length === 0;

  return (
    <div className="panel palette-panel">
      <div className="panel-header">
        <div>
          <h3>Node Library</h3>
          <p>Pick a registered node and drop it into your canvas.</p>
        </div>
      </div>
      <div className="palette-search">
        <input
          placeholder="Search nodes by name or type"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search registered nodes"
        />
      </div>
      <div className="palette-list">
        {filteredNodeTypes.map((nodeType) => (
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
        {isLoading && (
          <p className="palette-empty">Loading node registry from backend...</p>
        )}
        {showNoMatches && (
          <p className="palette-empty">
            No nodes match "{query.trim()}".
          </p>
        )}
      </div>
    </div>
  );
};

export default NodePalette;

