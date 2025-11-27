import React, { useState, useCallback } from "react";
import { ExecutionStats, ExecutionTraceEntry, NodeExecutionStatus } from "../types";
import ExecutionTimeline from "./ExecutionTimeline";
import PerformanceDashboard from "./PerformanceDashboard";

type LogPanelProps = {
  trace: ExecutionTraceEntry[];
  outputs: Record<string, unknown>;
  error: string | null;
  stats?: ExecutionStats | null;
  levels?: string[][];
  isRunning?: boolean;
  currentNodeId?: string | null;
  nodeStatuses?: Map<string, NodeExecutionStatus>;
  progress?: number;
  onHighlightNodes?: (nodeIds: string[]) => void;
};

type TabType = "outputs" | "timeline" | "performance";

// Extract node_id from output key (format: "node_id.port_name")
const extractNodeId = (outputKey: string): string | null => {
  const lastDotIndex = outputKey.lastIndexOf(".");
  if (lastDotIndex > 0) {
    return outputKey.substring(0, lastDotIndex);
  }
  return null;
};

const LogPanel = ({ 
  trace, 
  outputs, 
  error,
  stats = null,
  levels = [],
  isRunning = false,
  currentNodeId = null,
  nodeStatuses = new Map(),
  progress = 0,
  onHighlightNodes,
}: LogPanelProps) => {
  const [activeTab, setActiveTab] = useState<TabType>("timeline");

  const outputEntries = Object.entries(outputs);
  const hasOutputs = outputEntries.length > 0;
  const hasTrace = trace.length > 0;

  const handleOutputHover = useCallback((outputKey: string | null) => {
    if (onHighlightNodes) {
      if (outputKey) {
        const nodeId = extractNodeId(outputKey);
        onHighlightNodes(nodeId ? [nodeId] : []);
      } else {
        onHighlightNodes([]);
      }
    }
  }, [onHighlightNodes]);

  return (
    <div className="log-panel">
      <div className="log-header">
        <h3>Execution</h3>
        <div className="log-header-right">
          {isRunning && (
            <div className="execution-progress">
              <div className="progress-bar">
                <div 
                  className="progress-fill" 
                  style={{ width: `${progress * 100}%` }}
                />
              </div>
              <span className="progress-text">{Math.round(progress * 100)}%</span>
            </div>
          )}
          {error && <span className="log-error-badge">Error</span>}
        </div>
      </div>

      <div className="log-tabs">
        <button
          type="button"
          className={`log-tab ${activeTab === "timeline" ? "active" : ""}`}
          onClick={() => setActiveTab("timeline")}
        >
          Timeline {hasTrace && `(${trace.length})`}
        </button>
        <button
          type="button"
          className={`log-tab ${activeTab === "performance" ? "active" : ""}`}
          onClick={() => setActiveTab("performance")}
        >
          Performance
        </button>
        <button
          type="button"
          className={`log-tab ${activeTab === "outputs" ? "active" : ""}`}
          onClick={() => setActiveTab("outputs")}
        >
          Outputs {hasOutputs && `(${outputEntries.length})`}
        </button>
      </div>

      <div className="log-content">
        {activeTab === "timeline" && (
          <ExecutionTimeline
            trace={trace}
            stats={stats}
            levels={levels}
            isRunning={isRunning}
            currentNodeId={currentNodeId}
            nodeStatuses={nodeStatuses}
            onHighlightNodes={onHighlightNodes}
          />
        )}

        {activeTab === "performance" && (
          <PerformanceDashboard
            stats={stats}
            trace={trace}
            levels={levels}
            isRunning={isRunning}
            onHighlightNodes={onHighlightNodes}
          />
        )}

        {activeTab === "outputs" && (
          <div className="log-section">
            {hasOutputs ? (
              <div className="output-grid">
                {outputEntries.map(([key, value]) => (
                  <div 
                    key={key} 
                    className="output-item hoverable"
                    onMouseEnter={() => handleOutputHover(key)}
                    onMouseLeave={() => handleOutputHover(null)}
                  >
                    <span className="output-item-key">{key}</span>
                    <span className="output-item-value" title={JSON.stringify(value)}>
                      {JSON.stringify(value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">No outputs captured yet</div>
            )}
          </div>
        )}

        {error && (
          <div className="log-section">
            <div className="log-section-header">
              <h4>Error</h4>
            </div>
            <div className="trace-item" style={{ borderColor: "rgba(248, 81, 73, 0.4)" }}>
              <div className="trace-log" style={{ color: "#f85149", borderColor: "#f85149" }}>
                {error}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default LogPanel;
