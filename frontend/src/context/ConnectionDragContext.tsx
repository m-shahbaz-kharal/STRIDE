import React, { createContext, useContext, useMemo } from "react";

import { PortCompatibility } from "../hooks/useConnectionValidation";

// Phase 3 §7.1 — Drag-from-port port highlighting
//
// Broadcasts the currently active connection drag (or null) so every
// `BlueprintNode` can decide how to render its ports without forcing a
// full `nodes` array rebuild on every drag start. The classifier is a
// pure function that the host (App.tsx) wires up to the result of
// `useConnectionValidation`.
export interface ConnectionDragInfo {
  // The handle the user grabbed.
  nodeId: string;
  handleId: string;
  handleType: "source" | "target";
}

export interface ConnectionDragContextValue {
  drag: ConnectionDragInfo | null;
  // Returns "neutral" when no drag is active.
  classifyPort: (
    candidateNodeId: string,
    candidateHandleId: string,
    candidateDirection: "input" | "output"
  ) => PortCompatibility;
}

const NEUTRAL_VALUE: ConnectionDragContextValue = {
  drag: null,
  classifyPort: () => "neutral",
};

const ConnectionDragContext =
  createContext<ConnectionDragContextValue>(NEUTRAL_VALUE);

export const ConnectionDragProvider = ({
  drag,
  classifyPort,
  children,
}: {
  drag: ConnectionDragInfo | null;
  classifyPort: ConnectionDragContextValue["classifyPort"];
  children: React.ReactNode;
}) => {
  // Memoise so consumers re-render only when the drag identity changes
  // (drag start / drag end), not on every mouse move.
  const value = useMemo<ConnectionDragContextValue>(
    () => ({ drag, classifyPort }),
    [drag, classifyPort]
  );

  return (
    <ConnectionDragContext.Provider value={value}>
      {children}
    </ConnectionDragContext.Provider>
  );
};

export const useConnectionDrag = (): ConnectionDragContextValue =>
  useContext(ConnectionDragContext);
