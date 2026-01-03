import React, { useEffect, useRef, useState } from "react";
import { CloseIcon } from "./Icons";

interface AppDialogProps {
    isOpen: boolean;
    variant: "alert" | "confirm" | "prompt";
    title: string;
    message?: string;
    defaultValue?: string;
    placeholder?: string;
    confirmLabel?: string;
    cancelLabel?: string;
    danger?: boolean;
    onConfirm: (value?: string) => void;
    onCancel: () => void;
}

const AppDialog: React.FC<AppDialogProps> = ({
    isOpen,
    variant,
    title,
    message,
    defaultValue = "",
    placeholder = "",
    confirmLabel,
    cancelLabel = "Cancel",
    danger = false,
    onConfirm,
    onCancel,
}) => {
    const [inputValue, setInputValue] = useState(defaultValue);
    const inputRef = useRef<HTMLInputElement>(null);
    const confirmBtnRef = useRef<HTMLButtonElement>(null);

    // Reset input value when dialog opens with new defaultValue
    useEffect(() => {
        if (isOpen) {
            setInputValue(defaultValue);
        }
    }, [isOpen, defaultValue]);

    // Auto-focus input or confirm button
    useEffect(() => {
        if (!isOpen) return;
        setTimeout(() => {
            if (variant === "prompt" && inputRef.current) {
                inputRef.current.focus();
                inputRef.current.select();
            } else if (confirmBtnRef.current) {
                confirmBtnRef.current.focus();
            }
        }, 50);
    }, [isOpen, variant]);

    // Keyboard handling
    useEffect(() => {
        if (!isOpen) return;

        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                e.preventDefault();
                onCancel();
            } else if (e.key === "Enter" && variant !== "prompt") {
                e.preventDefault();
                onConfirm();
            }
        };

        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [isOpen, variant, onConfirm, onCancel]);

    if (!isOpen) return null;

    const handleSubmit = (e: React.FormEvent) => {
        e.preventDefault();
        if (variant === "prompt") {
            onConfirm(inputValue);
        } else {
            onConfirm();
        }
    };

    const getConfirmLabel = () => {
        if (confirmLabel) return confirmLabel;
        switch (variant) {
            case "alert":
                return "OK";
            case "confirm":
                return "Confirm";
            case "prompt":
                return "Submit";
            default:
                return "OK";
        }
    };

    const showCancelButton = variant !== "alert";

    return (
        <div className="modal-overlay" onClick={onCancel}>
            <div
                className={`modal-card ${danger ? "danger" : ""}`}
                onClick={(e) => e.stopPropagation()}
            >
                <div className="modal-header">
                    <h3>{title}</h3>
                    <button type="button" className="icon-btn" onClick={onCancel}>
                        <CloseIcon />
                    </button>
                </div>

                <form onSubmit={handleSubmit} style={{ display: "flex", flexDirection: "column", gap: "16px" }}>
                    <div className="modal-body">
                        {message && <p style={{ margin: 0 }}>{message}</p>}
                        {variant === "prompt" && (
                            <label style={{ display: "grid", gap: "6px" }}>
                                <input
                                    ref={inputRef}
                                    type="text"
                                    value={inputValue}
                                    onChange={(e) => setInputValue(e.target.value)}
                                    placeholder={placeholder}
                                />
                            </label>
                        )}
                    </div>

                    <div className="modal-actions">
                        {showCancelButton && (
                            <button type="button" className="ghost-btn" onClick={onCancel}>
                                {cancelLabel}
                            </button>
                        )}
                        <button
                            type="submit"
                            ref={confirmBtnRef}
                            className={danger ? "danger-btn" : "primary-btn"}
                        >
                            {getConfirmLabel()}
                        </button>
                    </div>
                </form>
            </div>
        </div>
    );
};

export default AppDialog;
