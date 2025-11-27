import React from "react";
import { ExecutionTraceEntry, ExecutionUnit } from "../types";

type LogPanelProps = {
  trace: ExecutionTraceEntry[];
  units: ExecutionUnit[];
  outputs: Record<string, unknown>;
  error: string | null;
};

const LogPanel = ({ trace, units, outputs, error }: LogPanelProps) => (
  <div className="panel log-panel">
    <div className="panel-header">
      <div>
        <h3>Live Logs & Tensor Watch</h3>
        <p>Trace your execution, inspect tensors, and keep an eye on units.</p>
      </div>
      {error && <span className="error-tag">{error}</span>}
    </div>

    <section className="log-section">
      <h4>Outputs</h4>
      <div className="output-grid">
        {Object.keys(outputs).length === 0 ? (
          <span className="empty-state">No outputs captured yet.</span>
        ) : (
          Object.entries(outputs).map(([key, value]) => (
            <div key={key} className="output-card">
              <strong>{key}</strong>
              <span>{JSON.stringify(value)}</span>
            </div>
          ))
        )}
      </div>
    </section>

    <section className="log-section">
      <h4>Execution Units</h4>
      <div className="unit-list">
        {units.map((unit, index) => (
          <div key={`${unit.device}-${index}`} className="unit-card">
            <div className="unit-card-header">
              <span>{unit.device.toUpperCase()}</span>
              <span>{unit.nodes.length} node(s)</span>
            </div>
            <small>{unit.nodes.map((node) => node.id).join(" → ")}</small>
          </div>
        ))}
        {units.length === 0 && <span className="empty-state">Planner hasn't run yet.</span>}
      </div>
    </section>

    <section className="log-section">
      <h4>Trace</h4>
      <div className="trace-list">
        {trace.map((entry) => (
          <div key={entry.node_id} className="trace-entry">
            <div className="trace-header">
              <strong>{entry.node_id}</strong>
              <span>{entry.device}</span>
            </div>
            <div className="trace-body">
              <p>
                <em>Outputs:</em> {JSON.stringify(entry.outputs)}
              </p>
              {entry.logs.map((log, index) => (
                <p key={`${entry.node_id}-log-${index}`} className="trace-log">
                  {log}
                </p>
              ))}
            </div>
          </div>
        ))}
        {trace.length === 0 && <span className="empty-state">No execution trace yet.</span>}
      </div>
    </section>
  </div>
);

export default LogPanel;

