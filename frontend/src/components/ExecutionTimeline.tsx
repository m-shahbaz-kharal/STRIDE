import React, { useCallback } from "react";
import { ExecutionStats, NodeExecutionStatus, NodeSummary } from "../types";

interface ExecutionTimelineProps {
  nodeSummaries: NodeSummary[];
  stats: ExecutionStats | null;
  levels: string[][];
  isRunning: boolean;
  currentNodeId: string | null;
  nodeStatuses: Map<string, NodeExecutionStatus>;
  onHighlightNodes?: (nodeIds: string[]) => void;
  onViewLog: (node: NodeSummary) => void;
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
        </div>
        <div className="entry-timing">
          <div className="entry-badges">
            {node.fromCache && <span className="entry-badge cached">Cached</span>}
            {/* Error badge removed as requested */}
          </div>
          {node.lastDurationMs !== undefined && (
            <span className="entry-duration">{formatDuration(node.lastDurationMs)}</span>
          )}
          {node.executionCount > 1 ? (
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
          ) : (
            <span
              style={{
                opacity: 0.5,
                fontSize: '10px',
                marginLeft: '6px',
                color: 'var(--text-muted)',
              }}
            >
              ×1
            </span>
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
          {(() => {
            const processedLogs = node.lastLogs.map(log => {
              if (log.includes('[ERROR]') || log.includes('ERROR:')) {
                let message = log;
                if (message.includes('[STACK TRACE]')) {
                  const parts = message.split('[STACK TRACE]');
                  message = parts[0];
                }
                message = message
                  .replace(/[\n\r]+/g, ' ')
                  .replace(/={10,}/g, '')
                  .replace('[ERROR]', '')
                  .replace('ERROR:', '')
                  .trim();

                return { message, isError: true, original: log };
              }
              return { message: log, isError: false, original: log };
            });

            const seen = new Set();
            const uniqueLogs = processedLogs.filter(item => {
              if (!item.message) return false;
              if (seen.has(item.message)) return false;
              seen.add(item.message);
              return true;
            });

            return uniqueLogs.map((item, index) => (
              <div key={index} className="entry-log">
                {item.isError ? (
                  <span style={{ color: 'var(--accent-red)', fontWeight: 500 }}>
                    {item.message}
                  </span>
                ) : (
                  item.message
                )}
              </div>
            ));
          })()}
        </div>
      )}
    </div>
  );
});

const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({
  nodeSummaries,
  stats,
  levels,
  isRunning,
  currentNodeId,
  nodeStatuses,
  onHighlightNodes,
  onViewLog
}) => {
  const cacheRate = React.useMemo(() => {
    if (!stats || stats.total_nodes === 0) return null;
    return (stats.cached_nodes / stats.total_nodes) * 100;
  }, [stats]);

  const levelStats = React.useMemo(() => {
    return levels.map((level, idx) => ({
      level: idx,
      nodeCount: level.length,
      nodes: level,
    }));
  }, [levels]);

  const hasData = nodeSummaries.length > 0 || stats !== null;

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
        {nodeSummaries.length > 0 && (
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', marginLeft: '8px' }}>
            {nodeSummaries.length} nodes
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
            onViewLog={onViewLog}
          />
        ))}
      </div>

      {stats && stats.error_nodes > 0 && (
        // Error summary is now handled in LogPanel
        null
      )}
    </div>
  );
};

// Memoize to prevent re-renders when parent state changes
export default React.memo(ExecutionTimeline);
