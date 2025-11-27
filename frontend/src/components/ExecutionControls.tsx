import React from "react";

type ExecutionControlsProps = {
  isRunning: boolean;
  selectionCount: number;
  breakpointCount: number;
  onRunGraph: () => void;
  onRunSelection: () => void;
  onStep: () => void;
  lastRunMode?: string;
};

const ExecutionControls = ({
  isRunning,
  selectionCount,
  breakpointCount,
  onRunGraph,
  onRunSelection,
  onStep,
  lastRunMode,
}: ExecutionControlsProps) => (
  <div className="panel controls-panel">
    <div className="panel-header">
      <div>
        <h3>Execution Controls</h3>
        <p>Drive the graph as if it were a live Blueprint.</p>
      </div>
    </div>
    <div className="control-buttons">
      <button type="button" onClick={onRunGraph} disabled={isRunning}>
        {isRunning ? "Running…" : "Run Graph"}
      </button>
      <button
        type="button"
        onClick={onRunSelection}
        disabled={isRunning || selectionCount === 0}
      >
        Run Selection ({selectionCount})
      </button>
      <button type="button" onClick={onStep} disabled={isRunning}>
        Step
      </button>
    </div>
    <div className="control-meta">
      <span>Breakpoints: {breakpointCount}</span>
      {lastRunMode && <span>Last mode: {lastRunMode}</span>}
    </div>
  </div>
);

export default ExecutionControls;

