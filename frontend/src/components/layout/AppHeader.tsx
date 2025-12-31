import React from "react";
import { PlayIcon, StopIcon, ClearCacheIcon, ConnectionIcon } from "../Icons";

interface HeaderTabsProps {
    activeTab: "graph-editor" | "outputs";
    onTabChange: (tab: "graph-editor" | "outputs") => void;
}

interface GraphSummary {
    nodeCount: number;
    edgeCount: number;
    selectedCount: number;
}

interface OutputsSummary {
    images: number;
    streams: number;
    values: number;
}

interface AppHeaderProps {
    headerTab: "graph-editor" | "outputs";
    onTabChange: (tab: "graph-editor" | "outputs") => void;
    graphSummary: GraphSummary;
    outputsSummary: OutputsSummary;
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
    outputsSummary,
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
                        className={`header-tab ${headerTab === "outputs" ? "active" : ""}`}
                        onClick={() => onTabChange("outputs")}
                    >
                        Outputs
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

                {headerTab === "outputs" && (
                    <div className="outputs-pills header-pills">
                        <span className="pill">
                            {outputsSummary.images} image{outputsSummary.images === 1 ? "" : "s"}
                        </span>
                        <span className="pill">
                            {outputsSummary.streams} stream{outputsSummary.streams === 1 ? "" : "s"}
                        </span>
                        <span className="pill">
                            {outputsSummary.values} value{outputsSummary.values === 1 ? "" : "s"}
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
