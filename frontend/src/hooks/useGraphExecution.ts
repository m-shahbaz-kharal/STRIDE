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
      params: Record<string, unknown>;
    }>;
    links: Array<{
      from_node: string;
      from_port: string;
      to_node: string;
      to_port: string;
    }>;
  };
  options: Record<string, unknown>;
}

interface UseGraphExecutionReturn {
  isConnected: boolean;
  isRunning: boolean;
  error: string | null;
  trace: ExecutionTraceEntry[];
  outputs: Record<string, unknown>;
  stats: ExecutionStats | null;
  levels: string[][];
  nodeStatuses: Map<string, NodeExecutionStatus>;
  currentNodeId: string | null;
  progress: number;
  executionId: string | null;
  runGraph: (payload: GraphPayload, runNodeIds?: string[]) => void;
  runGraphSync: (payload: GraphPayload, runNodeIds?: string[]) => Promise<ExecutionResult>;
  clearResults: () => void;
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

  const [isConnected, setIsConnected] = useState(false);
  const [activeRuns, setActiveRuns] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [trace, setTrace] = useState<ExecutionTraceEntry[]>([]);
  const [outputs, setOutputs] = useState<Record<string, unknown>>({});
  const [stats, setStats] = useState<ExecutionStats | null>(null);
  const [levels, setLevels] = useState<string[][]>([]);
  const [nodeStatuses, setNodeStatuses] = useState<Map<string, NodeExecutionStatus>>(new Map());
  const [currentNodeId, setCurrentNodeId] = useState<string | null>(null);
  const [progress, setProgress] = useState(0);
  const [executionId, setExecutionId] = useState<string | null>(null);

  // Handle incoming WebSocket messages
  const handleMessage = useCallback((event: MessageEvent) => {
    try {
      const data: ExecutionEvent = JSON.parse(event.data);

      switch (data.event_type) {
        case "start":
          setExecutionId(data.execution_id);
          setProgress(0);
          setTrace([]);
          setError(null);
          if (data.levels) {
            setLevels(data.levels);
          }
          if (data.execution_plan) {
            const initialStatuses = new Map<string, NodeExecutionStatus>();
            for (const node of data.execution_plan) {
              initialStatuses.set(node.node_id, "pending");
            }
            setNodeStatuses(initialStatuses);
          }
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
            setNodeStatuses((prev) => {
              const newMap = new Map(prev);
              const newStatus: NodeExecutionStatus =
                data.event_type === "node_skipped" ? "skipped" : "completed";
              newMap.set(data.node_id!, newStatus);
              return newMap;
            });
            setTrace((prev) => [
              ...prev,
              {
                node_id: data.node_id!,
                type: data.node_type ?? "",
                outputs: data.outputs ?? {},
                logs: data.logs ?? [],
                duration_ms: data.duration_ms,
                level: data.level,
                from_cache: data.from_cache,
              },
            ]);
          }
          if (data.progress !== undefined) {
            setProgress(data.progress);
          }
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
                logs: data.error ? [data.error] : [],
                duration_ms: data.duration_ms,
                level: data.level,
              },
            ]);
          }
          if (data.error) {
            setError(data.error);
          }
          break;

        case "complete":
          setCurrentNodeId(null);
          setProgress(1);
          activeRunRef.current = false;
          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;

        case "result":
          if (data.trace) setTrace(data.trace);
          if (data.outputs) setOutputs(data.outputs as Record<string, unknown>);
          if (data.stats) setStats(data.stats);
          if (data.levels) setLevels(data.levels as string[][]);
          setCurrentNodeId(null);
          setProgress(1);
          activeRunRef.current = false;
          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;

        case "error":
          setError(data.error ?? "Unknown error");
          setCurrentNodeId(null);
          activeRunRef.current = false;
          setActiveRuns((prev) => Math.max(0, prev - 1));
          break;
      }
    } catch (e) {
      console.error("Failed to parse WebSocket message:", e);
    }
  }, []);

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
    setTrace([]);
    setOutputs({});
    setStats(null);
    setProgress(0);
    setCurrentNodeId(null);
    setNodeStatuses((prev) => {
      const updated = new Map(prev);
      runNodeIds.forEach((id) => updated.set(id, "running"));
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
    setNodeStatuses((prev) => {
      const updated = new Map(prev);
      runNodeIds.forEach((id) => updated.set(id, "running"));
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
  }, []);

  return {
    isConnected,
    isRunning: activeRuns > 0,
    error,
    trace,
    outputs,
    stats,
    levels,
    nodeStatuses,
    currentNodeId,
    progress,
    executionId,
    runGraph,
    runGraphSync,
    clearResults,
  };
}
