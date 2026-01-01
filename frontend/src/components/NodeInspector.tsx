import React, { useMemo, useState, useCallback } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData } from "../types";
import { formatPortTypeLabel } from "../graph/utils";

type InspectorProps = {
  nodes: Node<BlueprintNodeData>[];
  onParamChange: (nodeId: string, param: string, value: string | number | boolean | null) => void;
  onDelete?: (nodeId: string) => void;
  onDuplicate?: (nodeId: string) => void;
  hoveredPort?: { nodeId: string; port: string; direction: "input" | "output" } | null;
  onPortHover?: (info: { nodeId: string; port: string; direction: "input" | "output" } | null) => void;
};

// Value display component with expand button
const PortValue = React.memo(({ value }: { value: unknown }) => {
  const [expanded, setExpanded] = useState(false);

  // Check for undefined/null first
  if (value === undefined || value === null) {
    return <span style={{ color: 'var(--text-muted)', fontStyle: 'italic', fontSize: '11px' }}>—</span>;
  }

  // Safe stringify
  let stringValue: string;
  try {
    stringValue = JSON.stringify(value);
  } catch {
    stringValue = String(value);
  }
  const isLong = stringValue.length > 50;

  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: '4px', flex: 1, minWidth: 0 }}>
      <span
        style={{
          fontFamily: 'monospace',
          fontSize: '11px',
          color: 'var(--text-secondary)',
          wordBreak: expanded ? 'break-all' : 'normal',
          overflow: expanded ? 'visible' : 'hidden',
          textOverflow: expanded ? 'clip' : 'ellipsis',
          whiteSpace: expanded ? 'pre-wrap' : 'nowrap',
          flex: 1,
          minWidth: 0,
        }}
        title={stringValue}
      >
        {stringValue}
      </span>
      {isLong && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          style={{
            background: 'rgba(139, 148, 158, 0.2)',
            border: 'none',
            borderRadius: '3px',
            padding: '1px 4px',
            color: 'var(--text-muted)',
            cursor: 'pointer',
            fontSize: '9px',
            flexShrink: 0,
          }}
        >
          {expanded ? '−' : '+'}
        </button>
      )}
    </div>
  );
});

// Single port row component
const PortRow = React.memo(({
  nodeId,
  portName,
  portType,
  direction,
  value,
  isHighlighted,
  onHover,
}: {
  nodeId: string;
  portName: string;
  portType: string;
  direction: "input" | "output";
  value: unknown;
  isHighlighted: boolean;
  onHover: (info: { nodeId: string; port: string; direction: "input" | "output" } | null) => void;
}) => (
  <div
    className={`inspector-port-row ${isHighlighted ? "highlighted" : ""}`}
    style={{
      display: 'flex',
      alignItems: 'flex-start',
      gap: '8px',
      padding: '6px 8px',
      borderRadius: '4px',
      backgroundColor: isHighlighted ? 'rgba(74, 158, 255, 0.15)' : 'rgba(255, 255, 255, 0.02)',
      marginBottom: '4px',
      transition: 'background-color 0.15s',
    }}
    onMouseEnter={() => onHover({ nodeId, port: portName, direction })}
    onMouseLeave={() => onHover(null)}
  >
    <div style={{ display: 'flex', flexDirection: 'column', minWidth: '80px', flexShrink: 0 }}>
      <span style={{
        color: isHighlighted ? 'var(--accent-blue)' : 'var(--text-primary)',
        fontSize: '12px',
        fontWeight: 500,
      }}>
        {portName}
      </span>
      <span style={{
        color: 'var(--text-muted)',
        fontSize: '10px',
      }}>
        {portType}
      </span>
    </div>
    <PortValue value={value} />
  </div>
));

// Single node inspector card
const NodeCard = ({
  node,
  onParamChange,
  onDelete,
  onDuplicate,
  isExpanded,
  onToggle,
  isSingleNode,
  hoveredPort,
  onPortHover,
}: {
  node: Node<BlueprintNodeData>;
  onParamChange: (nodeId: string, param: string, value: string | number | boolean | null) => void;
  onDelete?: (nodeId: string) => void;
  onDuplicate?: (nodeId: string) => void;
  isExpanded: boolean;
  onToggle: () => void;
  isSingleNode: boolean;
  hoveredPort?: { nodeId: string; port: string; direction: "input" | "output" } | null;
  onPortHover?: (info: { nodeId: string; port: string; direction: "input" | "output" } | null) => void;
}) => {
  const hasOutputs = node.data.last_outputs && Object.keys(node.data.last_outputs).length > 0;

  // Build input ports with values
  const inputPorts = useMemo(() => {
    const inputs = node.data.metadata?.inputs ?? [];
    const inputValues = node.data.inputValues ?? {};
    return inputs.map((input) => ({
      name: input.name,
      type: formatPortTypeLabel(input.type),
      value: inputValues[input.name],
    }));
  }, [node.data.metadata?.inputs, node.data.inputValues]);

  // Build output ports with last values
  const outputPorts = useMemo(() => {
    const outputs = node.data.metadata?.outputs ?? [];
    const lastOutputs = node.data.last_outputs ?? {};
    return outputs.map((output) => ({
      name: output.name,
      type: formatPortTypeLabel(output.type),
      value: lastOutputs[output.name],
    }));
  }, [node.data.metadata?.outputs, node.data.last_outputs]);

  const handlePortHover = useCallback((info: { nodeId: string; port: string; direction: "input" | "output" } | null) => {
    onPortHover?.(info);
  }, [onPortHover]);

  return (
    <div className={`inspector-node-card ${isSingleNode ? "single" : ""}`}>
      <div className="inspector-node-header" onClick={onToggle}>
        <div className="inspector-node-title">
          {!isSingleNode && (
            <svg
              className={`inspector-chevron ${isExpanded ? "expanded" : ""}`}
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="currentColor"
            >
              <path d="M10 6L8.59 7.41 13.17 12l-4.58 4.59L10 18l6-6z" />
            </svg>
          )}
          <div className="node-info">
            <span className="node-name">{node.data.displayName}</span>
            <span className="node-type">{node.data.nodeType}</span>
          </div>
        </div>
        <div className="inspector-node-actions">
          {hasOutputs && (
            <span className="output-indicator" title="Has cached outputs">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="currentColor">
                <path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm-2 15l-5-5 1.41-1.41L10 14.17l7.59-7.59L19 8l-9 9z" />
              </svg>
            </span>
          )}
          {onDuplicate && (
            <button
              type="button"
              className="inspector-action-btn"
              onClick={(e) => {
                e.stopPropagation();
                onDuplicate(node.id);
              }}
              title="Duplicate"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z" />
              </svg>
            </button>
          )}
          {onDelete && (
            <button
              type="button"
              className="inspector-action-btn delete"
              onClick={(e) => {
                e.stopPropagation();
                onDelete(node.id);
              }}
              title="Delete"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
                <path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {(isExpanded || isSingleNode) && (
        <div className="inspector-node-content">
          <div className="inspector-section">
            <h4>Info</h4>
            <div className="inspector-meta">
              <div>
                <span className="inspector-meta-label">Type</span>
                <span className="inspector-meta-value mono">{node.data.nodeType}</span>
              </div>
              {node.data.metadata?.category && (
                <div>
                  <span className="inspector-meta-label">Category</span>
                  <span className="inspector-meta-value">{node.data.metadata.category}</span>
                </div>
              )}
            </div>
            {node.data.description && (
              <p className="inspector-description">{node.data.description}</p>
            )}
          </div>

          {inputPorts.length > 0 && (
            <div className="inspector-section">
              <h4>Inputs</h4>
              <div className="inspector-ports">
                {inputPorts.map((port) => {
                  const isHighlighted =
                    hoveredPort?.nodeId === node.id &&
                    hoveredPort?.port === port.name &&
                    hoveredPort?.direction === "input";
                  return (
                    <PortRow
                      key={port.name}
                      nodeId={node.id}
                      portName={port.name}
                      portType={port.type}
                      direction="input"
                      value={port.value}
                      isHighlighted={isHighlighted}
                      onHover={handlePortHover}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {outputPorts.length > 0 && (
            <div className="inspector-section">
              <h4>Outputs</h4>
              <div className="inspector-ports">
                {outputPorts.map((port) => {
                  const isHighlighted =
                    hoveredPort?.nodeId === node.id &&
                    hoveredPort?.port === port.name &&
                    hoveredPort?.direction === "output";
                  return (
                    <PortRow
                      key={port.name}
                      nodeId={node.id}
                      portName={port.name}
                      portType={port.type}
                      direction="output"
                      value={port.value}
                      isHighlighted={isHighlighted}
                      onHover={handlePortHover}
                    />
                  );
                })}
              </div>
            </div>
          )}

          {inputPorts.length === 0 && outputPorts.length === 0 && !node.data.description && (
            <div className="inspector-empty">No ports defined</div>
          )}
        </div>
      )}
    </div>
  );
};

// PERF: Memoize NodeCard to prevent re-renders when other nodes change
const MemoizedNodeCard = React.memo(NodeCard);

const NodeInspector = ({
  nodes,
  onParamChange,
  onDelete,
  onDuplicate,
  hoveredPort,
  onPortHover,
}: InspectorProps) => {
  // Track expanded nodes in multi-select mode
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(new Set());

  const toggleNode = (nodeId: string) => {
    setExpandedNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) {
        next.delete(nodeId);
      } else {
        next.add(nodeId);
      }
      return next;
    });
  };

  if (nodes.length === 0) {
    return (
      <div className="inspector-panel">
        <div className="inspector-empty-state">
          <svg width="40" height="40" viewBox="0 0 24 24" fill="currentColor" style={{ opacity: 0.3 }}>
            <path d="M19.14 12.94c.04-.31.06-.63.06-.94 0-.31-.02-.63-.06-.94l2.03-1.58c.18-.14.23-.41.12-.61l-1.92-3.32c-.12-.22-.37-.29-.59-.22l-2.39.96c-.5-.38-1.03-.7-1.62-.94l-.36-2.54c-.04-.24-.24-.41-.48-.41h-3.84c-.24 0-.43.17-.47.41l-.36 2.54c-.59.24-1.13.57-1.62.94l-2.39-.96c-.22-.08-.47 0-.59.22L2.74 8.87c-.12.21-.08.47.12.61l2.03 1.58c-.04.31-.06.63-.06.94s.02.63.06.94l-2.03 1.58c-.18.14-.23.41-.12.61l1.92 3.32c.12.22.37.29.59.22l2.39-.96c.5.38 1.03.7 1.62.94l.36 2.54c.05.24.24.41.48.41h3.84c.24 0 .44-.17.47-.41l.36-2.54c.59-.24 1.13-.56 1.62-.94l2.39.96c.22.08.47 0 .59-.22l1.92-3.32c.12-.22.07-.47-.12-.61l-2.01-1.58zM12 15.6c-1.98 0-3.6-1.62-3.6-3.6s1.62-3.6 3.6-3.6 3.6 1.62 3.6 3.6-1.62 3.6-3.6 3.6z" />
          </svg>
          <p>Select a node to inspect</p>
          <span className="hint">Click a node or drag to select multiple</span>
        </div>
      </div>
    );
  }

  const isSingleNode = nodes.length === 1;

  return (
    <div className="inspector-panel">
      <div className="inspector-node-list">
        {nodes.map((node) => (
          <MemoizedNodeCard
            key={node.id}
            node={node}
            onParamChange={onParamChange}
            onDelete={onDelete}
            onDuplicate={onDuplicate}
            isExpanded={expandedNodes.has(node.id)}
            onToggle={() => toggleNode(node.id)}
            isSingleNode={isSingleNode}
            hoveredPort={hoveredPort}
            onPortHover={onPortHover}
          />
        ))}
      </div>
    </div>
  );
};

// Memoize to prevent re-renders when graph state changes
export default React.memo(NodeInspector);
