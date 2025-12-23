import React, { useEffect, useRef, useState } from "react";

interface LogsPopupProps {
  nodeId: string;
  nodeName: string;
  logs: string[];
  onClose: () => void;
}

const LogsPopup = ({ nodeId, nodeName, logs, onClose }: LogsPopupProps) => {
  const [size, setSize] = useState({ width: 450, height: 300 });
  const [position, setPosition] = useState({ x: window.innerWidth / 2 - 225, y: window.innerHeight / 2 - 150 });
  const [isDragging, setIsDragging] = useState(false);
  const [isResizing, setIsResizing] = useState(false);
  const dragStartRef = useRef({ x: 0, y: 0, posX: 0, posY: 0 });
  const resizeStartRef = useRef({ x: 0, y: 0, width: 0, height: 0 });

  useEffect(() => {
    const handleMouseMove = (e: MouseEvent) => {
      if (isDragging) {
        const dx = e.clientX - dragStartRef.current.x;
        const dy = e.clientY - dragStartRef.current.y;
        setPosition({
          x: dragStartRef.current.posX + dx,
          y: dragStartRef.current.posY + dy,
        });
      }
      if (isResizing) {
        const dx = e.clientX - resizeStartRef.current.x;
        const dy = e.clientY - resizeStartRef.current.y;
        setSize({
          width: Math.max(250, resizeStartRef.current.width + dx),
          height: Math.max(150, resizeStartRef.current.height + dy),
        });
      }
    };

    const handleMouseUp = () => {
      setIsDragging(false);
      setIsResizing(false);
    };

    if (isDragging || isResizing) {
      document.addEventListener("mousemove", handleMouseMove);
      document.addEventListener("mouseup", handleMouseUp);
    }

    return () => {
      document.removeEventListener("mousemove", handleMouseMove);
      document.removeEventListener("mouseup", handleMouseUp);
    };
  }, [isDragging, isResizing]);

  const handleDragStart = (e: React.MouseEvent) => {
    e.preventDefault();
    dragStartRef.current = { x: e.clientX, y: e.clientY, posX: position.x, posY: position.y };
    setIsDragging(true);
  };

  const handleResizeStart = (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    resizeStartRef.current = { x: e.clientX, y: e.clientY, width: size.width, height: size.height };
    setIsResizing(true);
  };

  return (
    <div className="value-popup-overlay" onClick={onClose}>
      <div
        className="value-popup logs-popup"
        style={{ left: position.x, top: position.y, width: size.width, height: size.height }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="value-popup-header" onMouseDown={handleDragStart}>
          <span className="value-popup-title">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" style={{ marginRight: 6 }}>
              <path d="M19 3H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2V5c0-1.1-.9-2-2-2zm-5 14H7v-2h7v2zm3-4H7v-2h10v2zm0-4H7V7h10v2z" />
            </svg>
            Logs: {nodeName}
          </span>
          <button className="value-popup-close" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
              <path d="M19 6.41L17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z" />
            </svg>
          </button>
        </div>
        <div className="value-popup-content logs-content">
          {logs.length === 0 ? (
            <div className="logs-empty">No logs available for this node.</div>
          ) : (
            logs.map((log, i) => (
              <div key={`${nodeId}-${i}`} className="log-line">
                <span className="log-line-number">{i + 1}</span>
                <span className="log-line-content">{log}</span>
              </div>
            ))
          )}
        </div>
        <div className="value-popup-resize" onMouseDown={handleResizeStart}>
          <svg width="10" height="10" viewBox="0 0 10 10">
            <path d="M9 1L1 9M9 5L5 9M9 9L9 9" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
          </svg>
        </div>
      </div>
    </div>
  );
};

export default LogsPopup;
