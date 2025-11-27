import React, { useMemo } from "react";
import { ExecutionStats, ExecutionTraceEntry } from "../types";

interface PerformanceDashboardProps {
  stats: ExecutionStats | null;
  trace: ExecutionTraceEntry[];
  levels: string[][];
  isRunning: boolean;
  onHighlightNodes?: (nodeIds: string[]) => void;
}

const formatDuration = (ms: number): string => {
  if (ms < 1) return "<1ms";
  if (ms < 1000) return `${ms.toFixed(1)}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

const PerformanceDashboard: React.FC<PerformanceDashboardProps> = ({
  stats,
  trace,
  levels,
  isRunning,
  onHighlightNodes,
}) => {
  // Calculate slowest nodes
  const slowestNodes = useMemo(() => {
    return [...trace]
      .filter((t) => t.duration_ms !== undefined)
      .sort((a, b) => (b.duration_ms ?? 0) - (a.duration_ms ?? 0))
      .slice(0, 5);
  }, [trace]);

  // Calculate level timing with node IDs
  const levelTiming = useMemo(() => {
    const levelData: Record<number, { count: number; totalTime: number; maxTime: number; nodes: string[] }> = {};
    
    for (const entry of trace) {
      const level = entry.level ?? 0;
      if (!levelData[level]) {
        levelData[level] = { count: 0, totalTime: 0, maxTime: 0, nodes: [] };
      }
      const duration = entry.duration_ms ?? 0;
      levelData[level].count++;
      levelData[level].totalTime += duration;
      levelData[level].maxTime = Math.max(levelData[level].maxTime, duration);
      levelData[level].nodes.push(entry.node_id);
    }
    
    // Also include nodes from levels that may not have trace entries yet
    levels.forEach((levelNodes, idx) => {
      if (!levelData[idx]) {
        levelData[idx] = { count: levelNodes.length, totalTime: 0, maxTime: 0, nodes: levelNodes };
      } else {
        // Merge with existing, preferring trace data but ensuring all nodes are listed
        const existingNodes = new Set(levelData[idx].nodes);
        levelNodes.forEach(nodeId => {
          if (!existingNodes.has(nodeId)) {
            levelData[idx].nodes.push(nodeId);
          }
        });
      }
    });
    
    return Object.entries(levelData)
      .map(([level, data]) => ({
        level: parseInt(level),
        ...data,
      }))
      .sort((a, b) => a.level - b.level);
  }, [trace, levels]);

  const handleNodeHover = (nodeId: string | null) => {
    if (onHighlightNodes) {
      onHighlightNodes(nodeId ? [nodeId] : []);
    }
  };

  const handleLevelHover = (nodes: string[] | null) => {
    if (onHighlightNodes) {
      onHighlightNodes(nodes ?? []);
    }
  };

  if (!stats && trace.length === 0) {
    return (
      <div className="performance-dashboard">
        <div className="dashboard-empty">
          <div className="empty-icon">📊</div>
          <div>Run graph to see performance metrics</div>
        </div>
      </div>
    );
  }

  const sequentialTime = stats?.node_time_ms ?? 0;
  const actualTime = stats?.total_time_ms ?? 0;
  const timeSaved = sequentialTime - actualTime;
  const timeSavedPercent = sequentialTime > 0 ? (timeSaved / sequentialTime) * 100 : 0;

  return (
    <div className="performance-dashboard">
      {isRunning && (
        <div className="dashboard-running">
          <div className="running-indicator">
            <span className="pulse-ring" />
            <span>Executing...</span>
          </div>
        </div>
      )}

      {stats && (
        <>
          {/* Main Stats */}
          <div className="dashboard-section">
            <h4>Execution Summary</h4>
            <div className="stats-grid main-stats">
              <div className="stat-item highlight">
                <div className="stat-value large">{formatDuration(stats.total_time_ms)}</div>
                <div className="stat-label">Total Execution Time</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.executed_nodes}</div>
                <div className="stat-label">Nodes Executed</div>
              </div>
              <div className="stat-item">
                <div className="stat-value">{stats.levels_executed}</div>
                <div className="stat-label">Levels</div>
              </div>
              {stats.error_nodes > 0 && (
                <div className="stat-item error">
                  <div className="stat-value">{stats.error_nodes}</div>
                  <div className="stat-label">Errors</div>
                </div>
              )}
            </div>
          </div>

          {/* Parallelism Stats */}
          <div className="dashboard-section">
            <h4>Parallelism Analysis</h4>
            <div className="parallelism-visual">
              <div className="parallelism-bar">
                <div className="parallelism-comparison">
                  <div className="comparison-bar sequential">
                    <div className="bar-fill" style={{ width: "100%" }} />
                    <span className="bar-label">Sequential: {formatDuration(sequentialTime)}</span>
                  </div>
                  <div className="comparison-bar actual">
                    <div 
                      className="bar-fill" 
                      style={{ width: `${actualTime / Math.max(sequentialTime, 1) * 100}%` }} 
                    />
                    <span className="bar-label">Parallel: {formatDuration(actualTime)}</span>
                  </div>
                </div>
              </div>
              <div className="stats-grid">
                <div className="stat-item success">
                  <div className="stat-value">{stats.parallel_efficiency.toFixed(2)}x</div>
                  <div className="stat-label">Speedup Factor</div>
                </div>
                <div className="stat-item">
                  <div className="stat-value">{stats.max_parallelism}</div>
                  <div className="stat-label">Max Parallelism</div>
                </div>
                {timeSaved > 0 && (
                  <div className="stat-item success">
                    <div className="stat-value">{timeSavedPercent.toFixed(0)}%</div>
                    <div className="stat-label">Time Saved</div>
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* Level Breakdown */}
          {levelTiming.length > 1 && (
            <div className="dashboard-section">
              <h4>Level Breakdown</h4>
              <div className="level-breakdown">
                {levelTiming.map(({ level, count, maxTime, nodes }) => (
                  <div 
                    key={level} 
                    className="level-item hoverable"
                    onMouseEnter={() => handleLevelHover(nodes)}
                    onMouseLeave={() => handleLevelHover(null)}
                  >
                    <div className="level-info">
                      <span className="level-name">Level {level}</span>
                      <span className="level-nodes">{count} node{count !== 1 ? "s" : ""}</span>
                    </div>
                    <div className="level-time">{formatDuration(maxTime)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Slowest Nodes */}
          {slowestNodes.length > 0 && (
            <div className="dashboard-section">
              <h4>Slowest Nodes</h4>
              <div className="slowest-nodes">
                {slowestNodes.map((entry, index) => (
                  <div 
                    key={entry.node_id} 
                    className="slowest-item hoverable"
                    onMouseEnter={() => handleNodeHover(entry.node_id)}
                    onMouseLeave={() => handleNodeHover(null)}
                  >
                    <div className="slowest-rank">{index + 1}</div>
                    <div className="slowest-info">
                      <div className="slowest-name">{entry.node_id}</div>
                      <div className="slowest-type">{entry.type}</div>
                    </div>
                    <div className="slowest-time">{formatDuration(entry.duration_ms ?? 0)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default PerformanceDashboard;
