import React, { useState } from "react";
import { ExecutionStats, ExecutionTraceEntry, NodeExecutionStatus } from "../types";
import ExecutionTimeline from "./ExecutionTimeline";
import PerformanceDashboard from "./PerformanceDashboard";

type LogPanelProps = {
  trace: ExecutionTraceEntry[];
  outputs: Record<string, unknown>;
  error: string | null;
  errorCode?: string | null;
  stats?: ExecutionStats | null;
  levels?: string[][];
  isRunning?: boolean;
  currentNodeId?: string | null;
  nodeStatuses?: Map<string, NodeExecutionStatus>;
  progress?: number;
  onHighlightNodes?: (nodeIds: string[]) => void;
};

type TabType = "timeline" | "performance";

const LogPanel = ({
  trace,
  outputs: _outputs, // Still accepted for API compatibility but not displayed
  error,
  errorCode,
  stats = null,
  levels = [],
  isRunning = false,
  currentNodeId = null,
  nodeStatuses = new Map(),
  progress = 0,
  onHighlightNodes,
}: LogPanelProps) => {
  const [activeTab, setActiveTab] = useState<TabType>("timeline");

  const hasTrace = trace.length > 0;

  return (
    <div className="log-panel">
      <div className="log-header">
        <h3>Execution</h3>
        <div className="log-header-right">
          {stats && (
            <div className="log-kpis">
              <span className="kpi-chip success">Cache {stats.cached_nodes}</span>
              <span className="kpi-chip">Parallel {stats.max_parallelism}x</span>
              {stats.skipped_nodes > 0 && (
                <span className="kpi-chip warn">Skipped {stats.skipped_nodes}</span>
              )}
              {stats.error_nodes > 0 && (
                <span className="kpi-chip error">Errors {stats.error_nodes}</span>
              )}
            </div>
          )}
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
          {error && <span className="log-error-badge">Error{errorCode ? ` (${errorCode})` : ""}</span>}
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

        {error && (
          <div className="log-section">
            <div className="log-section-header">
              <h4>Error</h4>
            </div>
            <div className="trace-item" style={{ borderColor: "rgba(248, 81, 73, 0.4)" }}>
              <div className="trace-log" style={{ color: "#f85149", borderColor: "#f85149" }}>
                {errorCode ? `[${errorCode}] ` : ""}{error}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

// Memoize to prevent re-renders when unrelated state changes
export default React.memo(LogPanel);
