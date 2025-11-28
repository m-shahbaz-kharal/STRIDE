import React, { useMemo, useState } from "react";
import { NodeTypeDefinition } from "../types";

type NodePaletteProps = {
  nodeTypes: NodeTypeDefinition[];
  onAddNode: (nodeType: NodeTypeDefinition) => void;
};

// Category icon component
const ChevronIcon = ({ collapsed }: { collapsed: boolean }) => (
  <svg
    className="category-icon"
    width="12"
    height="12"
    viewBox="0 0 24 24"
    fill="currentColor"
    style={{ transform: collapsed ? "rotate(-90deg)" : "rotate(0deg)" }}
  >
    <path d="M7.41 8.59L12 13.17l4.59-4.58L18 10l-6 6-6-6z" />
  </svg>
);

// Parse node type to extract category and node name
// e.g., "constant.number" -> { category: "Constant", nodeName: "Number" }
// e.g., "math.add" -> { category: "Math", nodeName: "Add" }
const parseNodeType = (nodeType: string): { category: string; nodeName: string } => {
  const parts = nodeType.split(".");
  if (parts.length >= 2) {
    // Capitalize first letter of category
    const category = parts[0].charAt(0).toUpperCase() + parts[0].slice(1).toLowerCase();
    // Join remaining parts and capitalize
    const nodeName = parts.slice(1).join(".").charAt(0).toUpperCase() + parts.slice(1).join(".").slice(1);
    return { category, nodeName };
  }
  // Fallback for node types without dot notation
  return { category: "Other", nodeName: nodeType };
};

const getCategoryForNodeType = (nodeType: string): string => {
  return parseNodeType(nodeType).category;
};

const NodePalette = ({ nodeTypes, onAddNode }: NodePaletteProps) => {
  const [query, setQuery] = useState("");
  const [collapsedCategories, setCollapsedCategories] = useState<Set<string>>(new Set());

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

  // Group nodes by category
  const categorizedNodes = useMemo(() => {
    const categories: Record<string, NodeTypeDefinition[]> = {};

    for (const nodeType of filteredNodeTypes) {
      const category = getCategoryForNodeType(nodeType.node_type);
      if (!categories[category]) {
        categories[category] = [];
      }
      categories[category].push(nodeType);
    }

    // Sort categories alphabetically, with "Other" always at the end
    const sortedCategories = Object.entries(categories).sort(([a], [b]) => {
      if (a === "Other") return 1;
      if (b === "Other") return -1;
      return a.localeCompare(b);
    });

    return sortedCategories;
  }, [filteredNodeTypes]);

  const toggleCategory = (category: string) => {
    setCollapsedCategories((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(category)) {
        newSet.delete(category);
      } else {
        newSet.add(category);
      }
      return newSet;
    });
  };

  const isLoading = nodeTypes.length === 0;
  const showNoMatches = !isLoading && filteredNodeTypes.length === 0;

  return (
    <div className="palette-panel">
      <div className="palette-header">
        <h3>Nodes</h3>
      </div>
      <div className="palette-search">
        <input
          placeholder="Search..."
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          aria-label="Search registered nodes"
        />
      </div>
      <div className="palette-list">
        {categorizedNodes.map(([category, nodes]) => {
          const isCollapsed = collapsedCategories.has(category);
          return (
            <div key={category} className="palette-category">
              <button
                type="button"
                className={`category-header ${isCollapsed ? "collapsed" : ""}`}
                onClick={() => toggleCategory(category)}
              >
                <ChevronIcon collapsed={isCollapsed} />
                <span>{category}</span>
                <span className="category-count">{nodes.length}</span>
              </button>
              <div className={`category-items ${isCollapsed ? "collapsed" : ""}`}>
                {nodes.map((nodeType) => (
                  <button
                    key={nodeType.node_type}
                    type="button"
                    className="palette-item"
                    onClick={() => onAddNode(nodeType)}
                    title={nodeType.description}
                    draggable
                    onDragStart={(event) => {
                      event.dataTransfer.setData("application/reactflow", JSON.stringify(nodeType));
                      event.dataTransfer.effectAllowed = "move";
                    }}
                  >
                    <span className="palette-item-name">{nodeType.display_name}</span>
                    <span className="palette-item-add">+</span>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
        {isLoading && (
          <p className="palette-empty">Loading nodes...</p>
        )}
        {showNoMatches && (
          <p className="palette-empty">
            No nodes match "{query.trim()}"
          </p>
        )}
      </div>
    </div>
  );
};

export default NodePalette;
