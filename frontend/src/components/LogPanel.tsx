import React, { useState } from "react";
import { ExecutionTraceEntry, ExecutionUnit } from "../types";

type LogPanelProps = {
  trace: ExecutionTraceEntry[];
  units: ExecutionUnit[];
  outputs: Record<string, unknown>;
  error: string | null;
};

type TabType = "outputs" | "trace" | "units";

const LogPanel = ({ trace, units, outputs, error }: LogPanelProps) => {
  const [activeTab, setActiveTab] = useState<TabType>("outputs");

  const outputEntries = Object.entries(outputs);
  const hasOutputs = outputEntries.length > 0;
  const hasTrace = trace.length > 0;
  const hasUnits = units.length > 0;

  return (
    <div className="log-panel">
      <div className="log-header">
        <h3>Logs</h3>
        {error && <span className="log-error-badge">Error</span>}
      </div>

      <div className="log-tabs">
        <button
          type="button"
          className={`log-tab ${activeTab === "outputs" ? "active" : ""}`}
          onClick={() => setActiveTab("outputs")}
        >
          Outputs {hasOutputs && `(${outputEntries.length})`}
        </button>
        <button
          type="button"
          className={`log-tab ${activeTab === "trace" ? "active" : ""}`}
          onClick={() => setActiveTab("trace")}
        >
          Trace {hasTrace && `(${trace.length})`}
        </button>
        <button
          type="button"
          className={`log-tab ${activeTab === "units" ? "active" : ""}`}
          onClick={() => setActiveTab("units")}
        >
          Units {hasUnits && `(${units.length})`}
        </button>
      </div>

      <div className="log-content">
        {activeTab === "outputs" && (
          <div className="log-section">
            {hasOutputs ? (
              <div className="output-grid">
                {outputEntries.map(([key, value]) => (
                  <div key={key} className="output-item">
                    <span className="output-item-key">{key}</span>
                    <span className="output-item-value" title={JSON.stringify(value)}>
                      {JSON.stringify(value)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">No outputs captured yet</div>
            )}
          </div>
        )}

        {activeTab === "trace" && (
          <div className="log-section">
            {hasTrace ? (
              <div className="trace-list">
                {trace.map((entry) => (
                  <div key={entry.node_id} className="trace-item">
                    <div className="trace-item-header">
                      <span className="trace-node-id">{entry.node_id}</span>
                      <span className="trace-device">{entry.device}</span>
                    </div>
                    <div className="trace-outputs">
                      → {JSON.stringify(entry.outputs)}
                    </div>
                    {entry.logs.length > 0 && entry.logs.map((log, index) => (
                      <div key={`${entry.node_id}-log-${index}`} className="trace-log">
                        {log}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">No execution trace yet</div>
            )}
          </div>
        )}

        {activeTab === "units" && (
          <div className="log-section">
            {hasUnits ? (
              <div className="unit-list">
                {units.map((unit, index) => (
                  <div key={`${unit.device}-${index}`} className="unit-item">
                    <div className="unit-item-header">
                      <span className="unit-device">{unit.device}</span>
                      <span className="unit-count">{unit.nodes.length} node(s)</span>
                    </div>
                    <div className="unit-nodes">
                      {unit.nodes.map((node) => node.id).join(" → ")}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">Planner hasn't run yet</div>
            )}
          </div>
        )}

        {error && (
          <div className="log-section">
            <div className="log-section-header">
              <h4>Error</h4>
            </div>
            <div className="trace-item" style={{ borderColor: "rgba(248, 81, 73, 0.4)" }}>
              <div className="trace-log" style={{ color: "#f85149", borderColor: "#f85149" }}>
                {error}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default LogPanel;
