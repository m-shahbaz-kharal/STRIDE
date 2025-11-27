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

// Map node types to categories
const getCategoryForNodeType = (nodeType: string): string => {
  const typeMapping: Record<string, string> = {
    // Math operations
    "addition": "Math",
    "subtraction": "Math",
    "multiplication": "Math",
    "division": "Math",
    "power": "Math",
    "sqrt": "Math",
    "abs": "Math",
    "mod": "Math",
    "floor": "Math",
    "ceil": "Math",
    "round": "Math",
    "min": "Math",
    "max": "Math",
    "clamp": "Math",
    "lerp": "Math",
    "sin": "Math",
    "cos": "Math",
    "tan": "Math",
    
    // Constants
    "constant": "Constants",
    "number": "Constants",
    "integer": "Constants",
    "float": "Constants",
    "string": "Constants",
    "boolean": "Constants",
    "pi": "Constants",
    "e": "Constants",
    
    // Logic
    "compare": "Logic",
    "and": "Logic",
    "or": "Logic",
    "not": "Logic",
    "xor": "Logic",
    "switch": "Logic",
    "branch": "Logic",
    "if": "Logic",
    
    // Flow control
    "loop": "Flow",
    "for": "Flow",
    "while": "Flow",
    "sequence": "Flow",
    "parallel": "Flow",
    
    // Data
    "array": "Data",
    "dict": "Data",
    "get": "Data",
    "set": "Data",
    "length": "Data",
    
    // Tensor operations
    "tensor": "Tensor",
    "reshape": "Tensor",
    "transpose": "Tensor",
    "matmul": "Tensor",
    "conv": "Tensor",
    "pool": "Tensor",
    
    // I/O
    "input": "I/O",
    "output": "I/O",
    "print": "I/O",
    "log": "I/O",
    "load": "I/O",
    "save": "I/O",
  };
  
  // Try exact match first
  if (typeMapping[nodeType.toLowerCase()]) {
    return typeMapping[nodeType.toLowerCase()];
  }
  
  // Try partial match
  const lowerType = nodeType.toLowerCase();
  for (const [key, category] of Object.entries(typeMapping)) {
    if (lowerType.includes(key)) {
      return category;
    }
  }
  
  return "Other";
};

// Category order priority
const categoryOrder = ["Math", "Constants", "Logic", "Flow", "Data", "Tensor", "I/O", "Other"];

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
    
    // Sort categories by priority order
    const sortedCategories: [string, NodeTypeDefinition[]][] = [];
    for (const cat of categoryOrder) {
      if (categories[cat]) {
        sortedCategories.push([cat, categories[cat]]);
        delete categories[cat];
      }
    }
    // Add remaining categories
    for (const [cat, nodes] of Object.entries(categories)) {
      sortedCategories.push([cat, nodes]);
    }
    
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
