import React from "react";

interface ConnectionToastProps {
    message: { text: string; tone: "error" | "info" } | null;
}

const ConnectionToast: React.FC<ConnectionToastProps> = ({ message }) => {
    if (!message) return null;

    return (
        <div className={`connection-toast ${message.tone}`}>
            <span className="connection-toast-dot" />
            <span className="connection-toast-text">{message.text}</span>
        </div>
    );
};

export default ConnectionToast;
