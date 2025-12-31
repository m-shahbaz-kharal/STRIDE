import { useCallback, useEffect, useRef, useState } from "react";

interface UseConnectionToastResult {
    message: { text: string; tone: "error" | "info" } | null;
    showMessage: (text: string, tone?: "error" | "info") => void;
    clearMessage: () => void;
}

export const useConnectionToast = (duration: number = 1800): UseConnectionToastResult => {
    const [message, setMessage] = useState<{ text: string; tone: "error" | "info" } | null>(null);
    const timeoutRef = useRef<number | null>(null);

    // Cleanup timeout on unmount
    useEffect(() => {
        return () => {
            if (timeoutRef.current) {
                window.clearTimeout(timeoutRef.current);
            }
        };
    }, []);

    const showMessage = useCallback((text: string, tone: "error" | "info" = "error") => {
        if (timeoutRef.current) {
            window.clearTimeout(timeoutRef.current);
        }
        setMessage({ text, tone });
        timeoutRef.current = window.setTimeout(() => setMessage(null), duration);
    }, [duration]);

    const clearMessage = useCallback(() => {
        if (timeoutRef.current) {
            window.clearTimeout(timeoutRef.current);
        }
        setMessage(null);
    }, []);

    return {
        message,
        showMessage,
        clearMessage,
    };
};
