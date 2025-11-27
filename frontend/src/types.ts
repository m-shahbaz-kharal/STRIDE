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
  params_schema: Record<string, ParamSchemaField>;
  params_defaults?: Record<string, string | number | boolean>;
}

export interface ExecutionTraceEntry {
  node_id: string;
  type: string;
  device: string;
  outputs: Record<string, unknown>;
  logs: string[];
}

export interface ExecutionUnit {
  device: string;
  nodes: Array<{ id: string; type: string }>;
}

export interface BlueprintNodeData {
  displayName: string;
  nodeType: string;
  description: string;
  input_ports: string[];
  output_ports: string[];
  params: Record<string, unknown>;
  device_hint: string;
  breakpoint: boolean;
  metadata?: NodeTypeDefinition;
  last_outputs?: Record<string, unknown>;
  last_device?: string;
}

