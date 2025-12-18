export type ParamSchemaType = "number" | "string" | "select";

export interface ParamSchemaField {
  type: ParamSchemaType;
  label?: string;
  description?: string;
  default?: string | number | boolean;
  options?: string[];
}

export interface NodeTypeDefinition {
  node_type: string;
  display_name: string;
  description: string;
  icon?: string;
  input_ports: string[];
  output_ports: string[];
  input_port_types?: Record<string, string>;
  output_port_types?: Record<string, string>;
  params_schema: Record<string, ParamSchemaField>;
  params_defaults?: Record<string, string | number | boolean>;
}

export type NodeExecutionStatus = 
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "skipped"
  | "error";

export interface ExecutionTraceEntry {
  node_id: string;
  type: string;
  outputs: Record<string, unknown>;
  logs: string[];
  duration_ms?: number;
  level?: number;
  from_cache?: boolean;
}

export interface ExecutionStats {
  total_nodes: number;
  executed_nodes: number;
  skipped_nodes: number;
  cached_nodes: number;
  error_nodes: number;
  total_time_ms: number;
  node_time_ms: number;
  parallel_efficiency: number;
  max_parallelism: number;
  levels_executed: number;
}

export interface ExecutionPlanNode {
  node_id: string;
  node_type: string;
  level: number;
}

export interface ExecutionEvent {
  event_type: 
    | "start"
    | "node_queued"
    | "node_started"
    | "node_completed"
    | "node_cached"
    | "node_error"
    | "complete"
    | "result"
    | "error";
  execution_id: string;
  timestamp: number;
  node_id?: string;
  node_type?: string;
  status?: NodeExecutionStatus;
  outputs?: Record<string, unknown>;
  logs?: string[];
  duration_ms?: number;
  error?: string;
  level?: number;
  progress?: number;
  total_nodes?: number;
  completed_nodes?: number;
  from_cache?: boolean;
  execution_plan?: ExecutionPlanNode[];
  levels?: string[][];
  // For result event
  trace?: ExecutionTraceEntry[];
  stats?: ExecutionStats;
}

export interface NodeExecutionState {
  status: NodeExecutionStatus;
  progress: number;
  startTime?: number;
  endTime?: number;
  duration_ms?: number;
  outputs?: Record<string, unknown>;
  error?: string;
}

export interface BlueprintNodeData {
  displayName: string;
  nodeType: string;
  description: string;
  input_ports: string[];
  output_ports: string[];
  input_port_types?: Record<string, string>;
  output_port_types?: Record<string, string>;
  params: Record<string, unknown>;
  breakpoint: boolean;
  metadata?: NodeTypeDefinition;
  last_outputs?: Record<string, unknown>;
  width?: number;
  height?: number;
  onDelete?: (nodeId: string) => void;
  onRunSelection?: (nodeId: string) => void;
  onClearCache?: (nodeId: string) => void;
  onInterrupt?: (nodeId: string) => void;
  // Execution state
  executionStatus?: NodeExecutionStatus;
  executionProgress?: number;
  executionDuration?: number;
  executionLogs?: string[];
  // Highlight state (for hover interactions from timeline/performance panels)
  isHighlighted?: boolean;
}

export interface ExecutionResult {
  outputs: Record<string, unknown>;
  trace: ExecutionTraceEntry[];
  stats?: ExecutionStats;
  levels?: string[][];
  execution_id?: string;
}
