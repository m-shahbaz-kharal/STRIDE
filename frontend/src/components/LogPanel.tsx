import React, { useState, useMemo, useCallback } from "react";
import { ExecutionStats, ExecutionTraceEntry, NodeExecutionStatus, NodeSummary } from "../types";
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

const formatDuration = (ms: number): string => {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

const LogPanel = ({
  trace,
  outputs: _outputs,
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

  // Calculate Node Summaries (Lifted from ExecutionTimeline)
  const nodeSummaries = useMemo(() => {
    const nodeMap = new Map<string, NodeSummary>();
    let maxDuration = 1;

    // First pass: aggregate data
    for (const entry of trace) {
      const duration = entry.duration_ms ?? 0;
      if (duration > maxDuration) maxDuration = duration;

      const existing = nodeMap.get(entry.node_id);
      if (existing) {
        existing.executionCount++;
        existing.lastDurationMs = entry.duration_ms;
        existing.totalDurationMs += duration;
        existing.lastOutputs = entry.outputs;
        existing.lastLogs = entry.logs;
        existing.lastError = entry.error ?? existing.lastError;
        existing.lastErrorDetails = entry.error_details ?? existing.lastErrorDetails;
        existing.fromCache = entry.from_cache ?? false;
        existing.hasErrors = existing.hasErrors || !!entry.error || entry.logs.some(l => l.toLowerCase().includes('error'));
      } else {
        // Calculate fallback display name if backend doesn't provide one
        const rawName = entry.type.split('.').pop()?.replace(/_/g, ' ') ?? entry.type;
        const fallbackName = rawName.split(' ').map(word =>
          word.charAt(0).toUpperCase() + word.slice(1).toLowerCase()
        ).join(' ');

        nodeMap.set(entry.node_id, {
          nodeId: entry.node_id,
          type: entry.type,
          displayName: entry.display_name ?? fallbackName,
          executionCount: 1,
          lastDurationMs: entry.duration_ms,
          totalDurationMs: duration,
          avgDurationMs: duration,
          lastOutputs: entry.outputs,
          lastLogs: entry.logs,
          lastError: entry.error,
          lastErrorDetails: entry.error_details,
          status: nodeStatuses.get(entry.node_id) ?? "completed",
          isActive: entry.node_id === currentNodeId,
          fromCache: entry.from_cache ?? false,
          hasErrors: !!entry.error || entry.logs.some(l => l.toLowerCase().includes('error')),
          level: entry.level,
          normalizedWidth: 0,
        });
      }
    }

    // Second pass: normalize widths and calculate averages
    for (const summary of nodeMap.values()) {
      summary.status = nodeStatuses.get(summary.nodeId) ?? "completed";
      summary.isActive = summary.nodeId === currentNodeId;
      summary.avgDurationMs = summary.totalDurationMs / summary.executionCount;
      summary.normalizedWidth = Math.max(0.1, (summary.lastDurationMs ?? 0) / maxDuration);
    }

    return Array.from(nodeMap.values());
  }, [trace, currentNodeId, nodeStatuses]); // Re-calculate when trace or status changes

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
            nodeSummaries={nodeSummaries}
            stats={stats}
            levels={levels}
            isRunning={isRunning}
            currentNodeId={currentNodeId}
            nodeStatuses={nodeStatuses}
            onHighlightNodes={onHighlightNodes}
            onViewLog={() => { }} // No-op as requested
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


      </div>
    </div>
  );
};

// Memoize to prevent re-renders when unrelated state changes
export default React.memo(LogPanel);
