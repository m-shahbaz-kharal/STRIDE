import React, { useMemo, useState, useCallback } from "react";
import { ExecutionTraceEntry, ExecutionStats, NodeExecutionStatus } from "../types";

interface ExecutionTimelineProps {
  trace: ExecutionTraceEntry[];
  stats: ExecutionStats | null;
  levels: string[][];
  isRunning: boolean;
  currentNodeId: string | null;
  nodeStatuses: Map<string, NodeExecutionStatus>;
  onHighlightNodes?: (nodeIds: string[]) => void;
}

// Aggregated node data - one entry per unique node
interface NodeSummary {
  nodeId: string;
  type: string;
  displayName: string;  // Exact display name from node definition
  executionCount: number;
  lastDurationMs: number | undefined;
  totalDurationMs: number;
  avgDurationMs: number;
  lastOutputs: Record<string, unknown>;
  lastLogs: string[];
  status: NodeExecutionStatus;
  isActive: boolean;
  fromCache: boolean;
  hasErrors: boolean;
  level: number | undefined;
  normalizedWidth: number;
  // All executions for the log dialog
  executions: ExecutionTraceEntry[];
}

const getStatusColor = (status: NodeExecutionStatus | undefined): string => {
  switch (status) {
    case "completed":
      return "var(--accent-green)";
    case "running":
      return "var(--status-running)";
    case "queued":
      return "var(--accent-orange)";
    case "error":
      return "var(--accent-red)";
    case "pending":
    default:
      return "var(--text-muted)";
  }
};

const formatDuration = (ms: number): string => {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

// Memoized node entry component - shows all data like before
const NodeEntry = React.memo(({
  node,
  onHover,
  onViewLog
}: {
  node: NodeSummary;
  onHover: (nodeId: string | null) => void;
  onViewLog: (node: NodeSummary) => void;
}) => {
  return (
    <div
      className={`timeline-entry ${node.status} ${node.isActive ? "active" : ""} hoverable`}
      onMouseEnter={() => onHover(node.nodeId)}
      onMouseLeave={() => onHover(null)}
    >
      <div className="entry-header">
        <div className="entry-info">
          <span className="entry-node-name" style={{ fontWeight: 500 }}>{node.displayName}</span>
          <span className="entry-node-id" style={{ color: 'var(--text-muted)', fontSize: '10px', marginLeft: '6px' }}>
            {node.nodeId}
          </span>
          {node.level !== undefined && (
            <span className="entry-level">L{node.level}</span>
          )}
          {node.executionCount > 1 && (
            <span
              style={{
                backgroundColor: 'rgba(74, 158, 255, 0.2)',
                color: 'var(--accent-blue, #4a9eff)',
                padding: '1px 6px',
                borderRadius: '10px',
                fontSize: '10px',
                marginLeft: '6px',
              }}
            >
              ×{node.executionCount}
            </span>
          )}
        </div>
        <div className="entry-timing">
          <div className="entry-badges">
            {node.fromCache && <span className="entry-badge cached">Cached</span>}
            {node.hasErrors && <span className="entry-badge error">Error</span>}
          </div>
          {node.lastDurationMs !== undefined && (
            <span className="entry-duration">{formatDuration(node.lastDurationMs)}</span>
          )}
          {node.executionCount > 1 && (
            <button
              type="button"
              onClick={(e) => {
                e.stopPropagation();
                onViewLog(node);
              }}
              style={{
                marginLeft: '8px',
                background: 'rgba(139, 148, 158, 0.2)',
                border: '1px solid rgba(139, 148, 158, 0.3)',
                borderRadius: '4px',
                padding: '2px 6px',
                color: 'var(--text-secondary, #c9d1d9)',
                cursor: 'pointer',
                fontSize: '10px',
              }}
            >
              View Log
            </button>
          )}
        </div>
      </div>

      <div className="entry-bar-container">
        <div
          className="entry-bar"
          style={{
            width: `${node.normalizedWidth * 100}%`,
            backgroundColor: getStatusColor(node.status),
          }}
        />
      </div>

      {node.lastLogs.length > 0 && (
        <div className="entry-logs">
          {node.lastLogs.map((log, logIndex) => (
            <div key={logIndex} className="entry-log">{log}</div>
          ))}
        </div>
      )}

      {Object.keys(node.lastOutputs).length > 0 && (
        <div className="entry-outputs">
          {Object.entries(node.lastOutputs).map(([key, value]) => (
            <div key={key} className="entry-output">
              <span className="output-key">{key}:</span>
              <span className="output-value">{JSON.stringify(value)}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
});
// Log dialog component - shows full execution history
const LogDialog = React.memo(({
  node,
  onClose
}: {
  node: NodeSummary | null;
  onClose: () => void;
}) => {
  if (!node) return null;

  return (
    <div
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        bottom: 0,
        backgroundColor: 'rgba(0, 0, 0, 0.7)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 10000,
      }}
      onClick={onClose}
    >
      <div
        style={{
          background: 'var(--bg-primary, #1a1f2e)',
          borderRadius: '8px',
          padding: '16px',
          width: '90%',
          maxWidth: '700px',
          maxHeight: '80vh',
          overflow: 'auto',
          border: '1px solid var(--border-color, #30363d)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ margin: 0, color: 'var(--text-primary, #fff)' }}>
              {node.nodeId}
            </h3>
            <div style={{ fontSize: '12px', color: 'var(--text-muted, #8b949e)', marginTop: '4px' }}>
              {node.executionCount} executions • Total: {formatDuration(node.totalDurationMs)} • Avg: {formatDuration(node.avgDurationMs)}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            style={{
              background: 'transparent',
              border: 'none',
              color: 'var(--text-muted, #8b949e)',
              cursor: 'pointer',
              fontSize: '24px',
              lineHeight: 1,
            }}
          >
            ×
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {node.executions.map((exec, idx) => (
            <div
              key={idx}
              style={{
                padding: '12px',
                background: 'rgba(255, 255, 255, 0.03)',
                borderRadius: '6px',
                border: '1px solid rgba(255, 255, 255, 0.05)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                <span style={{ color: 'var(--text-secondary, #c9d1d9)', fontWeight: 500 }}>
                  Run #{idx + 1}
                </span>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  {exec.from_cache && (
                    <span style={{ fontSize: '10px', padding: '2px 6px', borderRadius: '4px', background: 'rgba(63, 185, 80, 0.2)', color: '#3fb950' }}>
                      Cached
                    </span>
                  )}
                  <span style={{ color: 'var(--accent-blue, #4a9eff)', fontFamily: 'monospace' }}>
                    {exec.duration_ms !== undefined ? formatDuration(exec.duration_ms) : '-'}
                  </span>
                </div>
              </div>

              {exec.logs.length > 0 && (
                <div style={{ marginTop: '8px', padding: '8px', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>Logs:</div>
                  {exec.logs.map((log, logIdx) => (
                    <div key={logIdx} style={{ fontFamily: 'monospace', fontSize: '11px', color: 'var(--text-secondary)' }}>{log}</div>
                  ))}
                </div>
              )}

              {Object.keys(exec.outputs).length > 0 && (
                <div style={{ marginTop: '8px', padding: '8px', background: 'rgba(0,0,0,0.2)', borderRadius: '4px' }}>
                  <div style={{ fontSize: '10px', color: 'var(--text-muted)', marginBottom: '4px' }}>Outputs:</div>
                  {Object.entries(exec.outputs).map(([key, value]) => (
                    <div key={key} style={{ display: 'flex', gap: '8px', fontSize: '11px' }}>
                      <span style={{ color: 'var(--accent-blue)' }}>{key}:</span>
                      <span style={{ color: 'var(--text-secondary)', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                        {JSON.stringify(value)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});

const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({
  trace,
  stats,
  levels,
  isRunning,
  currentNodeId,
  nodeStatuses,
  onHighlightNodes,
}) => {
  const [logDialogNode, setLogDialogNode] = useState<NodeSummary | null>(null);

  // PERF: Aggregate trace entries by node - one entry per unique node
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
        existing.fromCache = entry.from_cache ?? false;
        existing.hasErrors = existing.hasErrors || entry.logs.some(l => l.toLowerCase().includes('error'));
        existing.executions.push(entry);
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
          status: nodeStatuses.get(entry.node_id) ?? "completed",
          isActive: entry.node_id === currentNodeId,
          fromCache: entry.from_cache ?? false,
          hasErrors: entry.logs.some(l => l.toLowerCase().includes('error')),
          level: entry.level,
          normalizedWidth: 0,
          executions: [entry],
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
  }, [trace, currentNodeId, nodeStatuses]);

  const cacheRate = useMemo(() => {
    if (!stats || stats.total_nodes === 0) return null;
    return (stats.cached_nodes / stats.total_nodes) * 100;
  }, [stats]);

  const levelStats = useMemo(() => {
    return levels.map((level, idx) => ({
      level: idx,
      nodeCount: level.length,
      nodes: level,
    }));
  }, [levels]);

  const hasData = trace.length > 0 || stats !== null;

  const handleNodeHover = useCallback((nodeId: string | null) => {
    if (onHighlightNodes) {
      onHighlightNodes(nodeId ? [nodeId] : []);
    }
  }, [onHighlightNodes]);

  const handleLevelHover = useCallback((nodes: string[] | null) => {
    if (onHighlightNodes) {
      onHighlightNodes(nodes ?? []);
    }
  }, [onHighlightNodes]);

  const handleViewLog = useCallback((node: NodeSummary) => {
    setLogDialogNode(node);
  }, []);

  const handleCloseLog = useCallback(() => {
    setLogDialogNode(null);
  }, []);

  return (
    <div className="execution-timeline">
      <div className="timeline-header">
        <h4>Execution Timeline</h4>
        {isRunning && (
          <div className="timeline-status running">
            <span className="pulse-dot" />
            Running
          </div>
        )}
        {trace.length > 0 && (
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '8px' }}>
            {nodeSummaries.length} nodes • {trace.length} total runs
          </span>
        )}
      </div>

      {stats && (
        <div className="timeline-stats-grid">
          <div className="stat-card">
            <div className="stat-value">{formatDuration(stats.total_time_ms)}</div>
            <div className="stat-label">Total Time</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.executed_nodes}/{stats.total_nodes}</div>
            <div className="stat-label">Nodes</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.parallel_efficiency.toFixed(2)}x</div>
            <div className="stat-label">Speedup</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.max_parallelism}</div>
            <div className="stat-label">Max Parallel</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.cached_nodes}</div>
            <div className="stat-label">Cache Hits{cacheRate !== null ? ` (${cacheRate.toFixed(0)}%)` : ""}</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.error_nodes}</div>
            <div className="stat-label">Errors</div>
          </div>
        </div>
      )}

      {levels.length > 0 && (
        <div className="timeline-levels">
          <div className="levels-header">
            <span>Parallel Levels</span>
            <span className="levels-count">{levels.length}</span>
          </div>
          <div className="levels-visualization">
            {levelStats.map(({ level, nodeCount, nodes }) => (
              <div
                key={level}
                className="level-bar-container hoverable"
                onMouseEnter={() => handleLevelHover(nodes)}
                onMouseLeave={() => handleLevelHover(null)}
              >
                <div className="level-label">L{level}</div>
                <div className="level-bar" style={{ "--node-count": nodeCount } as React.CSSProperties}>
                  {nodes.map((nodeId) => {
                    const status = nodeStatuses.get(nodeId);
                    return (
                      <div
                        key={nodeId}
                        className={`level-node ${status ?? "pending"} ${nodeId === currentNodeId ? "active" : ""}`}
                        title={nodeId}
                        style={{ backgroundColor: getStatusColor(status) }}
                        onMouseEnter={(e) => {
                          e.stopPropagation();
                          handleNodeHover(nodeId);
                        }}
                        onMouseLeave={(e) => {
                          e.stopPropagation();
                          handleNodeHover(null);
                        }}
                      />
                    );
                  })}
                </div>
                <div className="level-count">{nodeCount}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="timeline-trace">
        {!hasData && (
          <div className="timeline-empty">
            <div className="empty-icon">⚡</div>
            <div>Run graph to see execution timeline</div>
          </div>
        )}

        {nodeSummaries.map((node) => (
          <NodeEntry
            key={node.nodeId}
            node={node}
            onHover={handleNodeHover}
            onViewLog={handleViewLog}
          />
        ))}
      </div>

      {stats && stats.error_nodes > 0 && (
        <div className="timeline-errors">
          <span className="error-count">{stats.error_nodes} error(s)</span>
        </div>
      )}

      <LogDialog node={logDialogNode} onClose={handleCloseLog} />
    </div>
  );
};

// Memoize to prevent re-renders when parent state changes
export default React.memo(ExecutionTimeline);
