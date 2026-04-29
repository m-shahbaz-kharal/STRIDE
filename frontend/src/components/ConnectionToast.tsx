import React from "react";

import { ConnectionToastMessage } from "../hooks/useConnectionToast";

interface ConnectionToastProps {
    message: ConnectionToastMessage | null;
}

const ConnectionToast: React.FC<ConnectionToastProps> = ({ message }) => {
    if (!message) return null;

    return (
        <div className={`connection-toast ${message.tone}`}>
            <span className="connection-toast-dot" />
            <span className="connection-toast-text">{message.text}</span>
            {message.action && (
                <button
                    type="button"
                    className="connection-toast-action"
                    onClick={message.action.run}
                >
                    {message.action.label}
                </button>
            )}
        </div>
    );
};

export default ConnectionToast;
