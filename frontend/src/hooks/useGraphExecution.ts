import { useCallback, useEffect, useRef, useState } from "react";
import {
  ExecutionEvent,
  ExecutionResult,
  ExecutionStats,
  ExecutionTraceEntry,
  NodeExecutionStatus,
} from "../types";

interface GraphPayload {
  graph: {
    nodes: Array<{
      id: string;
      type: string;
      params?: Record<string, unknown>;
      input_values?: Record<string, unknown>;
      input_ports_override?: string[];
      input_port_types_override?: Record<string, unknown>;
      output_ports_override?: string[];
      output_port_types_override?: Record<string, unknown>;
      cache_enabled?: boolean;
    }>;
    links: Array<{
      from_node: string;
      from_port: string;
      to_node: string;
      to_port: string;
      kind?: "data" | "control";
    }>;
  };
  options: Record<string, unknown>;
}

interface UseGraphExecutionReturn {
  isConnected: boolean;
  isRunning: boolean;
  isInterrupting: boolean; // True while interruption is in progress
  hasRunningNodes: boolean; // True if any nodes are running/queued - for interrupt button
  error: string | null;
  errorCode?: string | null;
  trace: ExecutionTraceEntry[];
  outputs: Record<string, unknown>;
  stats: ExecutionStats | null;
  levels: string[][];
  nodeStatuses: Map<string, NodeExecutionStatus>;
  currentNodeId: string | null;
  progress: number;
  executionId: string | null; // Keeps the latest execution ID for backward compatibility
  activeExecutionIds: string[]; // List of all currently active execution IDs
  runGraph: (payload: GraphPayload, runNodeIds?: string[]) => void;
  runGraphSync: (payload: GraphPayload, runNodeIds?: string[]) => Promise<ExecutionResult>;
  clearResults: () => void;
  stop: () => Promise<void>; // Cancel all active executions
}

// Construct WebSocket URL - works with both Vite proxy and production
const getWebSocketUrl = (): string => {
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/run-graph`;
};

export function useGraphExecution(): UseGraphExecutionReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);
  const pendingPayloadRef = useRef<GraphPayload | null>(null);
  const activeRunRef = useRef(false);

  // Track active runs count in a ref for synchronous access in callbacks
  const activeRunsCountRef = useRef(0);
  // Track all active execution IDs
  const activeExecutionIdsRef = useRef<Set<string>>(new Set());

  const [isConnected, setIsConnected] = useState(false);
  const [activeRuns, setActiveRuns] = useState(0);
  const [isInterrupting, setIsInterrupting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [errorCode, setErrorCode] = useState<string | null>(null);
  const [trace, setTrace] = useState<ExecutionTraceEntry[]>([]);
  const [outputs, setOutputs] = useState<Record<string, unknown>>({});
  const [stats, setStats] = useState<ExecutionStats | null>(null);
  const [levels, setLevels] = useState<string[][]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Map<string, NodeExecutionStatus>>(new Map());
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [executionId, setExecutionId] = useState<string | null>(null);

  // Sync ref with state
  useEffect(() => {
    activeRunsCountRef.current = activeRuns;
  }, [activeRuns]);

  // PERF: Batch rapid updates during loops to prevent overwhelming React
  const pendingStatusUpdatesRef = useRef<Map<string, NodeExecutionStatus>>(new Map());
  const pendingTraceEntriesRef = useRef<ExecutionTraceEntry[]>([]);
  const pendingProgressRef = useRef<number | null>(null);
  const flushTimeoutRef = useRef<number | null>(null);
  const lastFlushTimeRef = useRef<number>(0);

  const THROTTLE_MS = 100; // Flush at most every 100ms during rapid events

  const flushPendingUpdates = useCallback(() => {
    const statusUpdates = pendingStatusUpdatesRef.current;
    const traceEntries = pendingTraceEntriesRef.current;
    const pendingProgress = pendingProgressRef.current;

    if (statusUpdates.size > 0) {
      setNodeStatuses((prev) => {
        const newMap = new Map(prev);
        statusUpdates.forEach((status, nodeId) => newMap.set(nodeId, status));
        return newMap;
      });
      pendingStatusUpdatesRef.current = new Map();
    }

    if (traceEntries.length > 0) {
      setTrace((prev) => [...prev, ...traceEntries]);
      pendingTraceEntriesRef.current = [];
    }

    if (pendingProgress !== null) {
      setProgress(pendingProgress);
      pendingProgressRef.current = null;
    }

    lastFlushTimeRef.current = Date.now();
    flushTimeoutRef.current = null;
  }, []);

  const scheduleFlush = useCallback(() => {
    if (flushTimeoutRef.current !== null) return; // Already scheduled

    const timeSinceLastFlush = Date.now() - lastFlushTimeRef.current;
    const delay = Math.max(0, THROTTLE_MS - timeSinceLastFlush);

    flushTimeoutRef.current = window.setTimeout(flushPendingUpdates, delay);
  }, [flushPendingUpdates]);

  // Handle incoming WebSocket messages
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data: ExecutionEvent = JSON.parse(event.data);

      // Track execution ID
      if (data.execution_id) {
        if (data.event_type === "start") {
          activeExecutionIdsRef.current.add(data.execution_id);
        } else if (data.event_type === "complete" || data.event_type === "error" || data.event_type === "result") {
          activeExecutionIdsRef.current.delete(data.execution_id);
        }
      }

      switch (data.event_type) {
        case "start":
          setExecutionId(data.execution_id);
          // Reset progress and errors for new run
          setProgress(0);
          setError(null);
          setErrorCode(null);
          if (data.levels) {
            setLevels(data.levels);
          }
          // IMPORTANT: Reset ALL node statuses first, then set execution_plan nodes to pending
          // This ensures loop body nodes (not in execution_plan) get cleared from previous runs
          setNodeStatuses((prev) => {
            // First, clear all statuses that are not "idle"
            // This resets loop body nodes that have stale statuses from previous interrupted runs
            const newMap = new Map<string, NodeExecutionStatus>();

            // Set all nodes from execution_plan to pending
            if (data.execution_plan) {
              // @ts-ignore - execution_plan is checked above
              for (const node of data.execution_plan) {
                newMap.set(node.node_id, "pending");
              }
            }
            return newMap;
          });
          break;

        case "node_queued":
          if (data.node_id) {
            setNodeStatuses((prev) => {
              const newMap = new Map(prev);
              newMap.set(data.node_id!, "queued");
              return newMap;
            });
          }
          break;

        case "node_started":
          if (data.node_id) {
            setCurrentNodeId(data.node_id);
            setNodeStatuses((prev) => {
              const newMap = new Map(prev);
              newMap.set(data.node_id!, "running");
              return newMap;
            });
          }
          break;

        case "node_completed":
        case "node_cached":
        case "node_skipped":
          if (data.node_id) {
            // PERF: Batch these updates during rapid loop execution
            const newStatus: NodeExecutionStatus =
              data.event_type === "node_skipped" ? "skipped" : "completed";
            pendingStatusUpdatesRef.current.set(data.node_id, newStatus);
            pendingTraceEntriesRef.current.push({
              node_id: data.node_id!,
              type: data.node_type ?? "",
              outputs: data.outputs ?? {},
              logs: data.logs ?? [],
              duration_ms: data.duration_ms,
              level: data.level,
              from_cache: data.from_cache,
            });
          }
          if (data.progress !== undefined) {
            pendingProgressRef.current = data.progress;
          }
          scheduleFlush();
          break;

        case "node_error":
          if (data.node_id) {
            setNodeStatuses((prev) => {
              const newMap = new Map(prev);
              newMap.set(data.node_id!, "error");
              return newMap;
            });
            setTrace((prev) => [
              ...prev,
              {
                node_id: data.node_id!,
                type: data.node_type ?? "",
                outputs: {},
                logs: data.logs ?? (data.error ? [`ERROR: ${data.error}`] : []),
                error: data.error,
                error_details: data.error_details,
                duration_ms: data.duration_ms,
                level: data.level,
              },
            ]);
          }
          if (data.error) {
            setError(data.error);
            setErrorCode(data.error_code ?? null);
          }
          break;

        case "complete":
          // Flush any pending updates before marking as complete
          flushPendingUpdates();

          if (activeRunsCountRef.current <= 1) {
            // Only clear statuses if this is the last run
            setNodeStatuses((prev) => {
              const updated = new Map(prev);
              for (const [nodeId, status] of updated) {
                if (status === "running" || status === "queued") {
                  updated.set(nodeId, "skipped");
                }
              }
              return updated;
            });
            setCurrentNodeId(null);
            setProgress(1);
            setExecutionId(null);
            activeRunRef.current = false;
            setIsInterrupting(false);
          }

          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;

        case "result":
          // Flush any pending updates before setting final results
          flushPendingUpdates();
          if (data.trace) setTrace(data.trace);
          if (data.outputs) setOutputs(data.outputs as Record<string, unknown>);
          if (data.stats) setStats(data.stats);
          if (data.levels) setLevels(data.levels as string[][]);

          if (activeRunsCountRef.current <= 1) {
            // Only clear statuses if this is the last run
            setNodeStatuses((prev) => {
              const updated = new Map(prev);
              for (const [nodeId, status] of updated) {
                if (status === "running" || status === "queued") {
                  updated.set(nodeId, "skipped");
                }
              }
              return updated;
            });
            setCurrentNodeId(null);
            setProgress(1);
            setExecutionId(null);
            activeRunRef.current = false;
            setIsInterrupting(false);
          }

          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;

        case "error":
          setError(data.error ?? "Unknown error");
          setErrorCode(data.error_code ?? null);

          if (activeRunsCountRef.current <= 1) {
            // Only clear statuses if this is the last run
            setNodeStatuses((prev) => {
              const updated = new Map(prev);
              for (const [nodeId, status] of updated) {
                if (status === "running" || status === "queued") {
                  updated.set(nodeId, "skipped");
                }
              }
              return updated;
            });
            setCurrentNodeId(null);
            setExecutionId(null);
            activeRunRef.current = false;
            setIsInterrupting(false);
          }

          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;
      }
    } catch (e) {
      console.error("Failed to parse WebSocket message:", e);
    }
  }, [scheduleFlush, flushPendingUpdates]);

  // Connect to WebSocket
  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      return;
    }

    try {
      const ws = new WebSocket(getWebSocketUrl());

      ws.onopen = () => {
        setIsConnected(true);
        setError(null);
        activeRunRef.current = false;

        if (pendingPayloadRef.current) {
          ws.send(JSON.stringify(pendingPayloadRef.current));
          pendingPayloadRef.current = null;
        }
      };

      ws.onclose = () => {
        setIsConnected(false);
        wsRef.current = null;
        if (activeRunRef.current) {
          activeRunRef.current = false;
          setActiveRuns(0);
          setError((prev) => prev ?? "Connection closed during execution");
        }
        // Clear active execution IDs on disconnect
        activeExecutionIdsRef.current.clear();
        setIsInterrupting(false);

        reconnectTimeoutRef.current = window.setTimeout(() => {
          connect();
        }, 2000);
      };

      ws.onerror = () => {
        setIsConnected(false);
        if (activeRunRef.current) {
          activeRunRef.current = false;
          setActiveRuns((prev) => Math.max(0, prev - 1));
          setError("WebSocket connection error");
        }
        activeExecutionIdsRef.current.clear();
        setIsInterrupting(false);
      };

      ws.onmessage = handleMessage;

      wsRef.current = ws;
    } catch (e) {
      console.error("WebSocket connection error:", e);
    }
  }, [handleMessage]);

  // Initialize connection
  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  // Run graph via WebSocket
  const runGraph = useCallback((payload: GraphPayload, runNodeIds: string[] = []) => {
    setActiveRuns((prev) => prev + 1);
    setError(null);

    // Only clear previous results if this is a full graph run
    if (runNodeIds.length === 0) {
      setTrace([]);
      setOutputs({});
      setStats(null);
      setProgress(0);
      setExecutionId(null);
      setCurrentNodeId(null);
      activeExecutionIdsRef.current.clear();
    }
    // For partial runs, we keep the old state context to allow concurrent visualization

    setNodeStatuses((prev) => {
      const updated = new Map(prev);
      runNodeIds.forEach((id) => updated.set(id, "queued"));
      return updated;
    });
    activeRunRef.current = true;

    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(payload));
    } else {
      pendingPayloadRef.current = payload;
      connect();
    }
  }, [connect]);

  // Run graph via HTTP (fallback)
  const runGraphSync = useCallback(async (payload: GraphPayload, runNodeIds: string[] = []): Promise<ExecutionResult> => {
    setActiveRuns((prev) => prev + 1);
    setError(null);
    setTrace([]);
    setOutputs({});
    setStats(null);
    setProgress(0);
    setExecutionId(null);
    activeExecutionIdsRef.current.clear();
    setNodeStatuses((prev) => {
      const updated = new Map(prev);
      runNodeIds.forEach((id) => updated.set(id, "queued"));
      return updated;
    });

    try {
      const response = await fetch("/api/run-graph-async", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        const message = await response.text();
        throw new Error(message || "Graph execution failed");
      }

      const data: ExecutionResult = await response.json();

      setTrace(data.trace ?? []);
      setOutputs(data.outputs ?? {});
      setStats(data.stats ?? null);
      setLevels(data.levels ?? []);
      setProgress(1);

      const statuses = new Map<string, NodeExecutionStatus>(nodeStatuses);
      for (const entry of data.trace ?? []) {
        statuses.set(entry.node_id, "completed");
      }
      runNodeIds.forEach((id) => {
        if (!statuses.has(id)) {
          statuses.set(id, "completed");
        }
      });
      setNodeStatuses(statuses);

      return data;
    } catch (e) {
      const message = e instanceof Error ? e.message : "Unknown error";
      setError(message);
      throw e;
    } finally {
      setActiveRuns((prev) => Math.max(0, prev - 1));
    }
  }, [nodeStatuses]);

  // Clear results
  const clearResults = useCallback(() => {
    setTrace([]);
    setOutputs({});
    setStats(null);
    setLevels([]);
    setNodeStatuses(new Map());
    setCurrentNodeId(null);
    setProgress(0);
    setError(null);
    setExecutionId(null);
    activeRunRef.current = false;
    setActiveRuns(0);
    setIsInterrupting(false);
    activeExecutionIdsRef.current.clear();
  }, []);

  // Compute hasRunningNodes: true if any node has running/queued status
  // This is used for the interrupt button when executionId might already be cleared
  const hasRunningNodes = Array.from(nodeStatuses.values()).some(
    (status) => status === "running" || status === "queued"
  );

  // Stop/Cancel all active executions
  const stop = useCallback(async () => {
    const ids = Array.from(activeExecutionIdsRef.current);
    if (ids.length === 0 && executionId) {
      ids.push(executionId);
    }

    if (ids.length === 0) return;

    // Set interrupting state immediately for responsive UI feedback
    setIsInterrupting(true);

    // Immediately flush any pending updates to show current state
    flushPendingUpdates();

    // Mark all currently running/queued nodes as "interrupting" visually
    setNodeStatuses((prev) => {
      const updated = new Map(prev);
      for (const [nodeId, status] of updated) {
        if (status === "running" || status === "queued") {
          // Keep as running but the isInterrupting flag will show visual feedback
        }
      }
      return updated;
    });

    await Promise.all(ids.map(async (id) => {
      try {
        await fetch(`/api/executions/${id}/cancel`, { method: "POST" });
      } catch (e) {
        console.error(`Failed to cancel execution ${id}:`, e);
      }
    }));

    // Note: isInterrupting will be cleared when we receive completion events
  }, [executionId, flushPendingUpdates]);

  // Clear isInterrupting after timeout if backend doesn't respond
  useEffect(() => {
    if (!isInterrupting) return;
    const timeout = window.setTimeout(() => {
      setIsInterrupting(false);
      setActiveRuns(0);
    }, 15000);
    return () => clearTimeout(timeout);
  }, [isInterrupting]);

  return {
    isConnected,
    isRunning: activeRuns > 0,
    isInterrupting,
    hasRunningNodes,
    error,
    errorCode,
    trace,
    outputs,
    stats,
    levels,
    nodeStatuses,
    currentNodeId,
    progress,
    executionId,
    activeExecutionIds: Array.from(activeExecutionIdsRef.current),
    runGraph,
    runGraphSync,
    clearResults,
    stop,
  };
}
