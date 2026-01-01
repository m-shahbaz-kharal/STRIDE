import React from "react";
import { PlayIcon, StopIcon, ClearCacheIcon, ConnectionIcon } from "../Icons";

interface HeaderTabsProps {
    activeTab: "graph-editor" | "display";
    onTabChange: (tab: "graph-editor" | "display") => void;
}

interface GraphSummary {
    nodeCount: number;
    edgeCount: number;
    selectedCount: number;
}

interface DisplaySummary {
    sections: number;
    totalItems: number;
}

interface AppHeaderProps {
    headerTab: "graph-editor" | "display";
    onTabChange: (tab: "graph-editor" | "display") => void;
    graphSummary: GraphSummary;
    displaySummary: DisplaySummary;
    isRunning: boolean;
    isConnected: boolean;
    progress: number;
    error: string | null;
    executionId: string | null;
    nodesCount: number;
    onRunGraph: () => void;
    onInterruptAll: () => void;
    onClearCache: () => void;
}

const AppHeader: React.FC<AppHeaderProps> = ({
    headerTab,
    onTabChange,
    graphSummary,
    displaySummary,
    isRunning,
    isConnected,
    progress,
    error,
    executionId,
    nodesCount,
    onRunGraph,
    onInterruptAll,
    onClearCache,
}) => {
    return (
        <header className="overlay-header">
            <div className="header-left">
                <div className="header-tabs">
                    <button
                        type="button"
                        className={`header-tab ${headerTab === "graph-editor" ? "active" : ""}`}
                        onClick={() => onTabChange("graph-editor")}
                    >
                        Graph Editor
                    </button>
                    <button
                        type="button"
                        className={`header-tab ${headerTab === "display" ? "active" : ""}`}
                        onClick={() => onTabChange("display")}
                    >
                        Display
                    </button>
                </div>

                {headerTab === "graph-editor" && (
                    <div className="outputs-pills header-pills">
                        <span className="pill">
                            {graphSummary.nodeCount} node{graphSummary.nodeCount === 1 ? "" : "s"}
                        </span>
                        <span className="pill">
                            {graphSummary.edgeCount} edge{graphSummary.edgeCount === 1 ? "" : "s"}
                        </span>
                        <span className="pill">{graphSummary.selectedCount} selected</span>
                    </div>
                )}

                {headerTab === "display" && (
                    <div className="outputs-pills header-pills">
                        <span className="pill">
                            {displaySummary.sections} section{displaySummary.sections === 1 ? "" : "s"}
                        </span>
                        <span className="pill">
                            {displaySummary.totalItems} item{displaySummary.totalItems === 1 ? "" : "s"}
                        </span>
                    </div>
                )}

                {headerTab === "graph-editor" && isRunning && (
                    <div className="header-stats">
                        <span className="stat-badge running">
                            <span className="pulse-dot" />
                            {Math.round(progress * 100)}%
                        </span>
                    </div>
                )}
            </div>

            {headerTab === "graph-editor" && (
                <div className="header-controls">
                    <ConnectionIcon connected={isConnected} />
                    <button
                        className="icon-btn primary"
                        onClick={onRunGraph}
                        disabled={nodesCount === 0}
                        title="Run Graph"
                    >
                        <PlayIcon />
                        {isRunning && <span className="btn-spinner" />}
                    </button>
                    <button
                        className="icon-btn danger"
                        onClick={onInterruptAll}
                        disabled={!isRunning || !executionId}
                        title="Interrupt all running nodes"
                    >
                        <StopIcon />
                    </button>
                    <button
                        className="icon-btn clear-cache-btn"
                        onClick={onClearCache}
                        disabled={isRunning}
                        title="Clear Backend Cache"
                    >
                        <ClearCacheIcon />
                    </button>
                    {error && (
                        <span className="error-indicator" title={error}>
                            !
                        </span>
                    )}
                </div>
            )}
        </header>
    );
};

export default AppHeader;



