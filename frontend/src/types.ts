

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
  // Allow additional backend properties
  [key: string]: unknown;
}

export interface PortDefinition {
  name: string;
  type: TypeDescriptor;
  required?: boolean;
  default?: unknown;
  description?: string;
  ui?: Record<string, unknown>;
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
  error?: string;
  error_details?: string;  // Full stacktrace for debugging
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

export interface NodeSummary {
  nodeId: string;
  type: string;
  displayName: string;  // Exact display name from node definition
  executionCount: number;
  lastDurationMs: number | undefined;
  totalDurationMs: number;
  avgDurationMs: number;
  lastOutputs: Record<string, unknown>;
  lastLogs: string[];
  lastError?: string;
  lastErrorDetails?: string;
  status: NodeExecutionStatus;
  isActive: boolean;
  fromCache: boolean;
  hasErrors: boolean;
  level: number | undefined;
  normalizedWidth: number;
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
  error_details?: string;  // Full stacktrace for debugging
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
  cacheEnabled?: boolean;  // Whether node outputs should be cached
  branchId?: string;  // Branch this node belongs to during execution
  isMergePoint?: boolean;  // Whether this node receives inputs from multiple branches
  onToggleControlPorts?: (nodeId: string) => void;  // Toggle control port visibility
  onToggleCache?: (nodeId: string) => void;  // Toggle node caching
  onTogglePublish?: (nodeId: string, portId: string, direction: "input" | "output", kind: any) => void; // Toggle port publication
  hoverControlPorts?: boolean;  // Temporary control port reveal during connection hover

  // Dashboard //
  published_ports?: Record<string, PublishedPortData>;
}

export interface PublishedPortData {
  alias: string;
  portId: string; // The internal port name (e.g. "camera", "input_1")
  kind: TypeKind;
  direction: "input" | "output";
}

export type WidgetType = "label" | "container" | "bound-input" | "bound-output" | "panel";

export interface DashboardWidget {
  id: string;
  type: WidgetType;
  label?: string; // User-defined label

  // Position & Size (grid units)
  x: number;
  y: number;
  w: number;
  h: number;
  zIndex?: number;

  // Binding info (if bound)
  nodeId?: string;
  portName?: string; // The original port name (e.g. "camera")

  // Style/Config
  style?: Record<string, unknown>;
  parentId?: string; // For nesting in containers
}


export interface DashboardLayout {
  widgets: DashboardWidget[];
  rootContainerId?: string; // If we want a specific root
  viewport?: { x: number; y: number; w: number; h: number; style?: Record<string, unknown> };
}

export interface ExecutionResult {
  outputs: Record<string, unknown>;
  trace: ExecutionTraceEntry[];
  stats?: ExecutionStats;
  levels?: string[][];
  execution_id?: string;
}
