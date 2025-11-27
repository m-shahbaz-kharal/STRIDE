import React from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, ParamSchemaField } from "../types";

type InspectorProps = {
  node?: Node<BlueprintNodeData>;
  onDeviceHintChange: (nodeId: string, hint: string) => void;
  onParamChange: (nodeId: string, param: string, value: string | number | boolean) => void;
  onToggleBreakpoint: (nodeId: string) => void;
};

const parseParamValue = (
  raw: string,
  schema: ParamSchemaField
): string | number | boolean => {
  if (schema.type === "number") {
    const numeric = Number(raw);
    return Number.isNaN(numeric) ? 0 : numeric;
  }
  if (schema.type === "select" && schema.options?.length) {
    return raw;
  }
  return raw;
};

const NodeInspector = ({
  node,
  onDeviceHintChange,
  onParamChange,
  onToggleBreakpoint,
}: InspectorProps) => {
  if (!node) {
    return (
      <div className="panel inspector-panel">
        <div className="panel-header">
          <h3>Node Inspector</h3>
        </div>
        <p className="panel-placeholder">Select a node to inspect its settings.</p>
      </div>
    );
  }

  const schema = node.data.metadata?.params_schema ?? {};
  const schemaEntries = Object.entries(schema);

  return (
    <div className="panel inspector-panel">
      <div className="panel-header">
        <div>
          <h3>{node.data.displayName}</h3>
          <p className="panel-subtitle">{node.data.nodeType}</p>
        </div>
      </div>
      <p className="panel-description">{node.data.description}</p>

      <div className="inspector-section">
        <label htmlFor="device-hint">Device Hint</label>
        <select
          id="device-hint"
          value={node.data.device_hint}
          onChange={(event) => onDeviceHintChange(node.id, event.target.value)}
        >
          <option value="auto">Auto</option>
          <option value="cpu">CPU</option>
          <option value="gpu">GPU</option>
        </select>
      </div>

      {schemaEntries.length > 0 && (
        <div className="inspector-section">
          <div className="inspector-section-header">
            <h4>Parameters</h4>
          </div>
          {schemaEntries.map(([param, field]) => (
            <label key={param} className="inspector-field">
              <span>{field.label ?? param}</span>
              {field.type === "select" && field.options ? (
                <select
                  value={`${node.data.params[param] ?? field.default ?? ""}`}
                  onChange={(event) =>
                    onParamChange(node.id, param, parseParamValue(event.target.value, field))
                  }
                >
                  {field.options.map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              ) : (
                <input
                  type={field.type === "number" ? "number" : "text"}
                  value={`${node.data.params[param] ?? field.default ?? ""}`}
                  onChange={(event) =>
                    onParamChange(node.id, param, parseParamValue(event.target.value, field))
                  }
                />
              )}
              {field.description && <small>{field.description}</small>}
            </label>
          ))}
        </div>
      )}

      <div className="inspector-section">
        <button
          type="button"
          className={node.data.breakpoint ? "ghost primary" : "ghost"}
          onClick={() => onToggleBreakpoint(node.id)}
        >
          {node.data.breakpoint ? "Clear Breakpoint" : "Set Breakpoint"}
        </button>
      </div>

      {node.data.last_outputs && (
        <div className="inspector-section">
          <div className="inspector-section-header">
            <h4>Last Outputs</h4>
          </div>
          <ul className="inspector-list">
            {Object.entries(node.data.last_outputs).map(([key, value]) => (
              <li key={key}>
                <strong>{key}:</strong> {JSON.stringify(value)}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default NodeInspector;

