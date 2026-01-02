export type ParamSchemaType = "number" | "float" | "int" | "string" | "select" | "boolean";

export type TypeKind =
  | "int"
  | "float"
  | "string"
  | "boolean"
  | "null"
  | "control"
  | "image"
  | "stream"
  | "url"
  | "any"
  | "unknown"
  | "list"
  | "map"
  | "record"
  | "tuple"
  | "option"
  | "tensor";

export interface TypeDescriptor {
  kind: TypeKind;
  name?: string;
  item?: TypeDescriptor;
  value?: TypeDescriptor;
  fields?: Record<string, TypeDescriptor>;
  nullable?: boolean;
  metadata?: Record<string, unknown>;
}

export interface PortDefinition {
  name: string;
  type: TypeDescriptor;
  required?: boolean;
  default?: unknown;
  description?: string;
  ui?: Record<string, unknown>;
}

export interface ParamSchemaField {
  type: ParamSchemaType;
  label?: string;
  description?: string;
  default?: string | number | boolean;
  options?: string[];
}

export interface NodeTypeDefinition {
  node_type: string;
  version?: string;
  display_name: string;
  category?: string;
  summary?: string;
  description: string;
  icon?: string;
  tags?: string[];
  stability?: "stable" | "experimental";
  inputs?: PortDefinition[];
  outputs?: PortDefinition[];
  // Legacy/compat fields for current UI usage
  input_ports: string[];
  output_ports: string[];
  input_port_types?: Record<string, TypeDescriptor | string>;
  output_port_types?: Record<string, TypeDescriptor | string>;
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
  display_name?: string;  // Exact display name from node definition
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
  branch_id?: string;  // Branch this node belongs to
  is_merge_point?: boolean;  // Whether node receives multi-branch inputs
}

export interface ExecutionEvent {
  event_type:
  | "start"
  | "node_queued"
  | "node_started"
  | "node_completed"
  | "node_cached"
  | "node_skipped"
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
  error_code?: string;
  level?: number;
  progress?: number;
  total_nodes?: number;
  completed_nodes?: number;
  from_cache?: boolean;
  execution_plan?: ExecutionPlanNode[];
  levels?: string[][];
  // Branch info for hybrid execution
  branches?: Record<string, string[]>;  // branch_id -> node_ids
  merge_points?: string[];  // List of merge point node_ids
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
  input_port_types?: Record<string, TypeDescriptor | string>;
  output_port_types?: Record<string, TypeDescriptor | string>;
  params: Record<string, unknown>;
  inputValues?: Record<string, unknown>;
  breakpoint: boolean;
  metadata?: NodeTypeDefinition;
  last_outputs?: Record<string, unknown>;
  width?: number;
  height?: number;
  onDelete?: (nodeId: string) => void;
  onRunSelection?: (nodeId: string) => void;
  onClearCache?: (nodeId: string) => void;
  onInterrupt?: (nodeId: string) => void;
  onParamChange?: (nodeId: string, param: string, value: string | number | boolean | null) => void;
  onPortHover?: (info: { nodeId: string; port: string; direction: "input" | "output" } | null) => void;
  onInputValueChange?: (nodeId: string, port: string, value: string | number | boolean | null) => void;
  onAddInputPort?: (nodeId: string) => void;
  highlightedPort?: { port: string; direction: "input" | "output" } | null;
  // Execution state
  executionStatus?: NodeExecutionStatus;
  executionProgress?: number;
  executionDuration?: number;
  executionLogs?: string[];
  // Highlight state (for hover interactions from timeline/performance panels)
  isHighlighted?: boolean;
  // Hybrid execution model
  executionMode?: "dataflow" | "controlflow";  // default: "dataflow"
  showControlPorts?: boolean;  // Whether to show control ports (default: false for dataflow)
  branchId?: string;  // Branch this node belongs to during execution
  isMergePoint?: boolean;  // Whether this node receives inputs from multiple branches
  onToggleControlPorts?: (nodeId: string) => void;  // Toggle control port visibility
  hoverControlPorts?: boolean;  // Temporary control port reveal during connection hover
}

export interface ExecutionResult {
  outputs: Record<string, unknown>;
  trace: ExecutionTraceEntry[];
  stats?: ExecutionStats;
  levels?: string[][];
  execution_id?: string;
}
