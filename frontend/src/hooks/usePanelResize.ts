import { useCallback, useEffect, useState } from "react";

interface UsePanelResizeOptions {
    leftMinWidth?: number;
    leftMaxWidth?: number;
    rightMinWidth?: number;
    rightMaxWidth?: number;
    defaultLeftWidth?: number;
    defaultRightWidth?: number;
}

export const usePanelResize = (options: UsePanelResizeOptions = {}) => {
    const {
        leftMinWidth = 180,
        leftMaxWidth = 400,
        rightMinWidth = 280,
        rightMaxWidth = 600,
        defaultLeftWidth = 260,
        defaultRightWidth = 340,
    } = options;

    const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
    const [rightPanelCollapsed, setRightPanelCollapsed] = useState(false);
    const [leftPanelWidth, setLeftPanelWidth] = useState(defaultLeftWidth);
    const [rightPanelWidth, setRightPanelWidth] = useState(defaultRightWidth);
    const [isResizingLeft, setIsResizingLeft] = useState(false);
    const [isResizingRight, setIsResizingRight] = useState(false);

    // Handle panel resizing
    useEffect(() => {
        const handleMouseMove = (e: MouseEvent) => {
            if (isResizingLeft) {
                const newWidth = Math.min(Math.max(leftMinWidth, e.clientX), leftMaxWidth);
                setLeftPanelWidth(newWidth);
            }
            if (isResizingRight) {
                const newWidth = Math.min(Math.max(rightMinWidth, window.innerWidth - e.clientX), rightMaxWidth);
                setRightPanelWidth(newWidth);
            }
        };

        const handleMouseUp = () => {
            setIsResizingLeft(false);
            setIsResizingRight(false);
        };

        if (isResizingLeft || isResizingRight) {
            document.addEventListener("mousemove", handleMouseMove);
            document.addEventListener("mouseup", handleMouseUp);
            document.body.style.cursor = "col-resize";
            document.body.style.userSelect = "none";
        }

        return () => {
            document.removeEventListener("mousemove", handleMouseMove);
            document.removeEventListener("mouseup", handleMouseUp);
            document.body.style.cursor = "";
            document.body.style.userSelect = "";
        };
    }, [isResizingLeft, isResizingRight, leftMinWidth, leftMaxWidth, rightMinWidth, rightMaxWidth]);

    const toggleLeftPanel = useCallback(() => {
        setLeftPanelCollapsed((prev) => !prev);
    }, []);

    const toggleRightPanel = useCallback(() => {
        setRightPanelCollapsed((prev) => !prev);
    }, []);

    const startResizingLeft = useCallback(() => {
        setIsResizingLeft(true);
    }, []);

    const startResizingRight = useCallback(() => {
        setIsResizingRight(true);
    }, []);

    const actualLeftWidth = leftPanelCollapsed ? 0 : leftPanelWidth;
    const actualRightWidth = rightPanelCollapsed ? 0 : rightPanelWidth;

    return {
        // State
        leftPanelCollapsed,
        rightPanelCollapsed,
        leftPanelWidth,
        rightPanelWidth,
        actualLeftWidth,
        actualRightWidth,
        isResizingLeft,
        isResizingRight,
        // Actions
        toggleLeftPanel,
        toggleRightPanel,
        startResizingLeft,
        startResizingRight,
        setLeftPanelCollapsed,
        setRightPanelCollapsed,
        setLeftPanelWidth,
        setRightPanelWidth,
    };
};
