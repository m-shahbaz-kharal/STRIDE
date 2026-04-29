

// Mirrors the kind values produced by stride-core's typesystem.py.
// Phase 0: extended to all backend kinds so PORT_TYPE_COLORS covers every
// kind that can flow on the wire. This is a *union*, not an enum — string
// literals like "url" remain valid at every existing call site. If you
// add a new kind in stride-core, add it here too.
//
// Reference: docs/architecture/unified-type-system-and-ux.md §3.5
export type TypeKind =
  // Scalars (PRIMITIVES in typesystem.py)
  | "int"
  | "float"
  | "string"
  | "boolean"
  | "null"
  // Containers
  | "list"
  | "map"
  | "record"
  | "tuple"
  | "option"
  // Flexible / categorical
  | "any"
  | "unknown"
  | "tensor"
  | "control"
  | "stream"
  // 2-D / image-domain
  | "image"
  | "mask"
  | "depthmap"
  | "bbox2d"
  | "track2d"
  | "keypoints"
  | "detections2d"
  // 3-D / point-cloud-domain
  | "pointcloud"
  | "bbox3d"
  | "track3d"
  | "region3d"
  | "scene3d"
  | "detections3d"
  // Special / resource
  | "point"
  | "box"
  | "session"
  // Frontend-only legacy aliases retained for backward compatibility with
  // existing widget code (e.g. URL string inputs). These are not produced
  // by the backend type registry but appear in saved widget configs.
  | "url";

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
  // Node parameters
  params_schema?: Record<string, unknown>;
  params_defaults?: Record<string, unknown>;
}

export type NodeExecutionStatus =
  | "pending"
  | "queued"
  | "running"
  | "completed"
  | "skipped"
  | "error";

// Phase 2 §6.3: structured payload that the runtime emits for every typed
// NodeError. Phase 2 plumbs the field through; Phase 3 will render it as an
// inline node badge with disclosure tooltips.
export interface NodeErrorPayload {
  code: string;
  message: string;
  node_id?: string;
  node_type?: string;
  port?: string | null;
  details?: Record<string, unknown>;
  stack_trace?: string;
}

export interface ExecutionTraceEntry {
  node_id: string;
  type: string;
  display_name?: string;  // Exact display name from node definition
  outputs: Record<string, unknown>;
  logs: string[];
  error?: string;
  error_code?: string;
  error_details?: string;  // Full stacktrace for debugging
  error_payload?: NodeErrorPayload;  // Structured NodeError payload (Phase 2)
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
  error_payload?: NodeErrorPayload;  // Structured NodeError payload (Phase 2 §6.3)
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
  params?: Record<string, unknown>;

  inputValues?: Record<string, unknown>;
  breakpoint?: boolean;
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
  inputType?: TypeKind; // For bound inputs, the expected type

  // Phase 4 §8.4: composition — render multiple bindings as a single overlay
  // (e.g. an image as primary plus detections2d/keypoints/mask overlays).
  // The primary binding is `(nodeId, portName)`; overlays add more.
  composition?: {
    overlays: Array<{ nodeId: string; portName: string }>;
  };
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
