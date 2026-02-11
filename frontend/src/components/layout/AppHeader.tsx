import React, { useEffect, useRef, useState } from "react";
import {
    PlayIcon,
    StopIcon,
    ClearCacheIcon,
    ConnectionIcon,
    HomeIcon,
    SaveIcon,
    UserIcon,
    SettingsIcon,
    LogoutIcon,
    CodeIcon,
    EyeIcon,
} from "../Icons";

interface GraphSummary {
    nodeCount: number;
    edgeCount: number;
    selectedCount: number;
}



interface AppHeaderProps {
    headerTab: "home" | "graph-editor" | "dashboard";
    onTabChange: (tab: "home" | "graph-editor" | "dashboard") => void;
    graphSummary: GraphSummary;
    graphName: string | null;
    isGraphDirty: boolean;
    isRunning: boolean;
    isInterrupting: boolean;
    isConnected: boolean;
    progress: number;
    error: string | null;
    executionId: string | null;
    nodesCount: number;
    jsonViewEnabled: boolean;
    onToggleJsonView: () => void;
    onRunGraph: () => void;
    onInterruptAll: () => void;
    onClearCache: () => void;
    onSaveGraph: () => void;
    onRenameGraph: () => void;
    onSignOut: () => void;
    onAccountSettings: () => void;
    hasRunningNodes: boolean;
}

const AppHeader: React.FC<AppHeaderProps> = ({
    headerTab,
    onTabChange,
    graphSummary,
    graphName,
    isGraphDirty,
    isRunning,
    isInterrupting,
    isConnected,
    progress,
    error,
    executionId,
    nodesCount,
    jsonViewEnabled,
    onToggleJsonView,
    onRunGraph,
    onInterruptAll,
    onClearCache,
    onSaveGraph,
    onRenameGraph,
    onSignOut,
    onAccountSettings,
    hasRunningNodes,
}) => {
    const [accountOpen, setAccountOpen] = useState(false);
    const accountRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClick = (event: MouseEvent) => {
            if (!accountRef.current) return;
            if (accountRef.current.contains(event.target as Node)) return;
            setAccountOpen(false);
        };
        document.addEventListener("mousedown", handleClick);
        return () => document.removeEventListener("mousedown", handleClick);
    }, []);

    return (
        <header className="overlay-header">
            <div className="header-left">
                <div className="header-home-group">
                    <button
                        type="button"
                        className={`header-home-tab ${headerTab === "home" ? "active" : ""}`}
                        onClick={() => onTabChange("home")}
                        title="Home"
                    >
                        <HomeIcon />
                    </button>
                    <span className="header-divider" />
                </div>

                {headerTab !== "home" && (
                    <div className="header-tabs">
                        <button
                            type="button"
                            className={`header-tab ${headerTab === "graph-editor" ? "active" : ""}`}
                            onClick={() => onTabChange("graph-editor")}
                        >
                            Graph Editor
                            <span
                                className={`tab-mode-toggle ${headerTab !== "graph-editor" ? "disabled" : ""}`}
                                onClick={(e) => {
                                    e.stopPropagation();
                                    if (headerTab !== "graph-editor") {
                                        onTabChange("graph-editor");
                                    } else {
                                        onToggleJsonView();
                                    }
                                }}
                                title={jsonViewEnabled ? "Switch to Visual Editor" : "Switch to JSON Viewer"}
                            >
                                {jsonViewEnabled ? <CodeIcon /> : <EyeIcon />}
                            </span>
                        </button>
                        <button
                            type="button"
                            className={`header-tab ${headerTab === "dashboard" ? "active" : ""}`}
                            onClick={() => onTabChange("dashboard")}
                        >
                            Dashboard
                        </button>
                    </div>
                )}

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



                {headerTab === "graph-editor" && isRunning && (
                    <div className="header-stats">
                        <span className={`stat-badge ${isInterrupting ? "interrupting" : "running"}`}>
                            <span className="pulse-dot" />
                            {isInterrupting ? "Stopping..." : `${Math.round(progress * 100)}%`}
                        </span>
                    </div>
                )}
            </div>

            <div className="header-center">
                {headerTab !== "home" && graphName && (
                    <div className="header-graph-status">
                        <button type="button" className="graph-title-btn" onClick={onRenameGraph}>
                            {graphName}
                        </button>
                        <span className={`graph-save-indicator ${isGraphDirty ? "dirty" : "clean"}`}>
                            {isGraphDirty ? "Unsaved" : "Saved"}
                        </span>
                    </div>
                )}
            </div>

            <div className="header-controls">
                {(headerTab === "graph-editor" || headerTab === "dashboard") && (
                    <>
                        <ConnectionIcon connected={isConnected} />
                        <button
                            className="icon-btn primary"
                            onClick={onRunGraph}
                            disabled={nodesCount === 0 || hasRunningNodes || jsonViewEnabled}
                            title="Run Graph"
                        >
                            <PlayIcon />
                            {isRunning && <span className="btn-spinner" />}
                        </button>
                        <button
                            className={`icon-btn danger ${isInterrupting ? "interrupting" : ""}`}
                            onClick={onInterruptAll}
                            disabled={!hasRunningNodes || isInterrupting}
                            title={isInterrupting ? "Interrupting..." : "Interrupt all running nodes"}
                        >
                            <StopIcon />
                            {isInterrupting && <span className="btn-spinner" />}
                        </button>
                        {headerTab !== "dashboard" && (
                            <button
                                className="icon-btn clear-cache-btn"
                                onClick={onClearCache}
                                disabled={isRunning}
                                title="Clear Backend Cache"
                            >
                                <ClearCacheIcon />
                            </button>
                        )}
                        {error && (
                            <span className="error-indicator" title={error}>
                                !
                            </span>
                        )}

                        <span className="header-divider" />

                        <button
                            className="icon-btn"
                            onClick={onSaveGraph}
                            disabled={!isGraphDirty}
                            title="Save graph"
                            style={{ color: isGraphDirty ? "var(--accent-orange)" : undefined }}
                        >
                            <SaveIcon />
                        </button>
                    </>
                )}
                <span className="header-divider" />
                <div className="account-menu" ref={accountRef}>
                    <button
                        type="button"
                        className="icon-btn"
                        onClick={() => setAccountOpen((prev) => !prev)}
                        title="Account"
                    >
                        <UserIcon />
                    </button>
                    {accountOpen && (
                        <div className="account-dropdown">
                            <button type="button" onClick={onAccountSettings}>
                                <span className="account-item-icon">
                                    <SettingsIcon />
                                </span>
                                Account settings
                            </button>
                            <button type="button" onClick={onSignOut}>
                                <span className="account-item-icon">
                                    <LogoutIcon />
                                </span>
                                Log out
                            </button>
                        </div>
                    )}
                </div>
            </div>
        </header>
    );
};

export default AppHeader;
