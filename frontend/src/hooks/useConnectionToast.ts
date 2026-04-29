import { useCallback, useEffect, useRef, useState } from "react";

// Phase 5 §4.7 — connection toast can carry an actionable button (e.g.
// "Insert <converter>") on top of the plain text message. The action is
// optional; when present, clicking it dismisses the toast.
export interface ConnectionToastAction {
    label: string;
    run: () => void;
}

export interface ConnectionToastMessage {
    text: string;
    tone: "error" | "info";
    action?: ConnectionToastAction;
}

interface UseConnectionToastResult {
    message: ConnectionToastMessage | null;
    showMessage: (
        text: string,
        toneOrOptions?: "error" | "info" | { tone?: "error" | "info"; action?: ConnectionToastAction },
    ) => void;
    clearMessage: () => void;
}

export const useConnectionToast = (duration: number = 4000): UseConnectionToastResult => {
    const [message, setMessage] = useState<ConnectionToastMessage | null>(null);
    const timeoutRef = useRef<number | null>(null);

    // Cleanup timeout on unmount
    useEffect(() => {
        return () => {
            if (timeoutRef.current) {
                window.clearTimeout(timeoutRef.current);
            }
        };
    }, []);

    const clearMessage = useCallback(() => {
        if (timeoutRef.current) {
            window.clearTimeout(timeoutRef.current);
        }
        setMessage(null);
    }, []);

    const showMessage = useCallback<UseConnectionToastResult["showMessage"]>(
        (text, toneOrOptions) => {
            if (timeoutRef.current) {
                window.clearTimeout(timeoutRef.current);
            }
            const opts =
                toneOrOptions && typeof toneOrOptions === "object"
                    ? toneOrOptions
                    : { tone: (toneOrOptions ?? "error") as "error" | "info" };
            const tone = opts.tone ?? "error";
            const action = opts.action;
            // Wrap the action so a click also dismisses the toast.
            const wrappedAction = action
                ? {
                      label: action.label,
                      run: () => {
                          clearMessage();
                          action.run();
                      },
                  }
                : undefined;
            setMessage({ text, tone, action: wrappedAction });
            timeoutRef.current = window.setTimeout(() => setMessage(null), duration);
        },
        [duration, clearMessage]
    );

    return {
        message,
        showMessage,
        clearMessage,
    };
};
