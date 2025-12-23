import React, { createContext, useCallback, useContext, useState } from "react";

import LogsPopup from "../components/LogsPopup";
import ValuePopup from "../components/ValuePopup";

type ValuePopupState = { value: unknown; title: string } | null;
type LogsPopupState = { nodeId: string; nodeName: string; logs: string[] } | null;

type PopupContextValue = {
  showValuePopup: (value: unknown, title: string) => void;
  showLogsPopup: (nodeId: string, nodeName: string, logs: string[]) => void;
};

const PopupContext = createContext<PopupContextValue | undefined>(undefined);

export const PopupProvider = ({ children }: { children: React.ReactNode }) => {
  const [valuePopup, setValuePopup] = useState<ValuePopupState>(null);
  const [logsPopup, setLogsPopup] = useState<LogsPopupState>(null);

  const showValuePopup = useCallback((value: unknown, title: string) => {
    setValuePopup({ value, title });
  }, []);

  const showLogsPopup = useCallback((nodeId: string, nodeName: string, logs: string[]) => {
    setLogsPopup({ nodeId, nodeName, logs });
  }, []);

  return (
    <PopupContext.Provider value={{ showValuePopup, showLogsPopup }}>
      {children}
      {valuePopup && (
        <ValuePopup
          value={valuePopup.value}
          title={valuePopup.title}
          onClose={() => setValuePopup(null)}
        />
      )}
      {logsPopup && (
        <LogsPopup
          nodeId={logsPopup.nodeId}
          nodeName={logsPopup.nodeName}
          logs={logsPopup.logs}
          onClose={() => setLogsPopup(null)}
        />
      )}
    </PopupContext.Provider>
  );
};

export const usePopups = (): PopupContextValue => {
  const context = useContext(PopupContext);
  if (!context) {
    throw new Error("usePopups must be used within a PopupProvider");
  }
  return context;
};
