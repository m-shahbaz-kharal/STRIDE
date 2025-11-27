import React from "react";
import { Node } from "reactflow";
import { BlueprintNodeData, ParamSchemaField } from "../types";

type InspectorProps = {
  node?: Node<BlueprintNodeData>;
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
  onParamChange,
  onToggleBreakpoint,
}: InspectorProps) => {
  if (!node) {
    return (
      <div className="inspector-panel">
        <h3>Inspector</h3>
        <p className="inspector-placeholder">Select a node to inspect</p>
      </div>
    );
  }

  const schema = node.data.metadata?.params_schema ?? {};
  const schemaEntries = Object.entries(schema);

  return (
    <div className="inspector-panel">
      <h3>{node.data.displayName}</h3>
      <div className="inspector-subtitle">{node.data.nodeType}</div>

      {schemaEntries.length > 0 && (
        <div className="inspector-section">
          <h4>Parameters</h4>
          {schemaEntries.map(([param, field]) => (
            <div key={param} className="inspector-field">
              <label htmlFor={`param-${param}`}>{field.label ?? param}</label>
              {field.type === "select" && field.options ? (
                <select
                  id={`param-${param}`}
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
                  id={`param-${param}`}
                  type={field.type === "number" ? "number" : "text"}
                  value={`${node.data.params[param] ?? field.default ?? ""}`}
                  onChange={(event) =>
                    onParamChange(node.id, param, parseParamValue(event.target.value, field))
                  }
                />
              )}
              {field.description && <small>{field.description}</small>}
            </div>
          ))}
        </div>
      )}

      <div className="inspector-section">
        <button
          type="button"
          className={`inspector-btn ${node.data.breakpoint ? "active" : ""}`}
          onClick={() => onToggleBreakpoint(node.id)}
        >
          {node.data.breakpoint ? "Clear Breakpoint" : "Set Breakpoint"}
        </button>
      </div>

      {node.data.last_outputs && (
        <div className="inspector-section">
          <h4>Last Outputs</h4>
          <div className="inspector-outputs">
            {Object.entries(node.data.last_outputs).map(([key, value]) => (
              <div key={key} className="inspector-output-item">
                <span className="inspector-output-key">{key}</span>
                <span className="inspector-output-value" title={JSON.stringify(value)}>
                  {JSON.stringify(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default NodeInspector;
