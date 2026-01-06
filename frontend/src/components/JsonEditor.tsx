import React from "react";
import "./JsonEditor.css";

interface JsonViewerProps {
    graphJson: string;
    onClose: () => void;
}

const JsonViewer: React.FC<JsonViewerProps> = ({ graphJson, onClose }) => {
    return (
        <div className="json-editor">
            <div className="json-editor-toolbar">
                <div className="json-editor-title">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
                        <path d="M9.4 16.6L4.8 12l4.6-4.6L8 6l-6 6 6 6 1.4-1.4zm5.2 0L19.2 12l-4.6-4.6L16 6l6 6-6 6-1.4-1.4z" />
                    </svg>
                    Graph JSON (Read-only)
                </div>
                <div className="json-editor-actions">
                    <button type="button" className="json-btn secondary" onClick={onClose}>
                        Close
                    </button>
                </div>
            </div>
            <textarea
                className="json-editor-textarea"
                value={graphJson}
                readOnly
                spellCheck={false}
            />
        </div>
    );
};

export default JsonViewer;
