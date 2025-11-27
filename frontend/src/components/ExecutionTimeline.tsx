import React, { useEffect, useRef, useMemo } from "react";
import { ExecutionTraceEntry, ExecutionStats, NodeExecutionStatus } from "../types";

interface ExecutionTimelineProps {
  trace: ExecutionTraceEntry[];
  stats: ExecutionStats | null;
  levels: string[][];
  isRunning: boolean;
  currentNodeId: string | null;
  nodeStatuses: Map<string, NodeExecutionStatus>;
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

const ExecutionTimeline: React.FC<ExecutionTimelineProps> = ({
  trace,
  stats,
  levels,
  isRunning,
  currentNodeId,
  nodeStatuses,
}) => {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current && isRunning) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [trace, isRunning]);

  const timelineData = useMemo(() => {
    if (trace.length === 0) return [];
    
    const maxTime = Math.max(...trace.map((t) => t.duration_ms ?? 1), 1);
    
    return trace.map((entry) => {
      const duration = entry.duration_ms ?? 0;
      const normalizedWidth = Math.max(0.1, duration / maxTime);
      const status = nodeStatuses.get(entry.node_id) ?? "completed";
      
      return {
        ...entry,
        normalizedWidth,
        status,
        isActive: entry.node_id === currentNodeId,
      };
    });
  }, [trace, currentNodeId, nodeStatuses]);

  const levelStats = useMemo(() => {
    return levels.map((level, idx) => ({
      level: idx,
      nodeCount: level.length,
      nodes: level,
    }));
  }, [levels]);

  const hasData = trace.length > 0 || stats !== null;

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
              <div key={level} className="level-bar-container">
                <div className="level-label">L{level}</div>
                <div className="level-bar" style={{ "--node-count": nodeCount } as React.CSSProperties}>
                  {nodes.map((nodeId) => {
                    const status = nodeStatuses.get(nodeId);
                    const traceEntry = trace.find((t) => t.node_id === nodeId);
                    return (
                      <div
                        key={nodeId}
                        className={`level-node ${status ?? "pending"} ${nodeId === currentNodeId ? "active" : ""}`}
                        title={`${nodeId}${traceEntry?.duration_ms ? ` (${formatDuration(traceEntry.duration_ms)})` : ""}`}
                        style={{ backgroundColor: getStatusColor(status) }}
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

      <div className="timeline-trace" ref={scrollRef}>
        {!hasData && (
          <div className="timeline-empty">
            <div className="empty-icon">⚡</div>
            <div>Run graph to see execution timeline</div>
          </div>
        )}
        
        {timelineData.map((entry, index) => (
          <div
            key={`${entry.node_id}-${index}`}
            className={`timeline-entry ${entry.status} ${entry.isActive ? "active" : ""}`}
          >
            <div className="entry-header">
              <div className="entry-info">
                <span className="entry-index">{index + 1}</span>
                <span className="entry-node-id">{entry.node_id}</span>
                {entry.level !== undefined && (
                  <span className="entry-level">L{entry.level}</span>
                )}
              </div>
              <div className="entry-timing">
                {entry.duration_ms !== undefined && (
                  <span className="entry-duration">{formatDuration(entry.duration_ms)}</span>
                )}
              </div>
            </div>
            
            <div className="entry-bar-container">
              <div
                className="entry-bar"
                style={{
                  width: `${entry.normalizedWidth * 100}%`,
                  backgroundColor: getStatusColor(entry.status),
                }}
              />
            </div>

            {entry.logs.length > 0 && (
              <div className="entry-logs">
                {entry.logs.map((log, logIndex) => (
                  <div key={logIndex} className="entry-log">{log}</div>
                ))}
              </div>
            )}

            {Object.keys(entry.outputs).length > 0 && (
              <div className="entry-outputs">
                {Object.entries(entry.outputs).map(([key, value]) => (
                  <div key={key} className="entry-output">
                    <span className="output-key">{key}:</span>
                    <span className="output-value">{JSON.stringify(value)}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      {stats && stats.error_nodes > 0 && (
        <div className="timeline-errors">
          <span className="error-count">{stats.error_nodes} error(s)</span>
        </div>
      )}
    </div>
  );
};

export default ExecutionTimeline;
