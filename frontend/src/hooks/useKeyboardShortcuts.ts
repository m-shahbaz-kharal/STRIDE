import { useCallback, useEffect, useState } from "react";

interface UseKeyboardShortcutsOptions {
    onDelete?: () => void;
    onSelectAll?: () => void;
    onDuplicate?: () => void;
    onCopy?: () => void;
    onPaste?: () => void;
    onUndo?: () => void;
    onRedo?: () => void;
    canDuplicate?: boolean;
    canCopy?: boolean;
}

export const useKeyboardShortcuts = (options: UseKeyboardShortcutsOptions) => {
    const {
        onDelete,
        onSelectAll,
        onDuplicate,
        onCopy,
        onPaste,
        onUndo,
        onRedo,
        canDuplicate = true,
        canCopy = true,
    } = options;

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            // Don't trigger shortcuts when typing in inputs
            const target = event.target as HTMLElement;
            if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT") {
                return;
            }

            const isCtrlOrCmd = event.ctrlKey || event.metaKey;

            // Delete selected nodes and edges
            if (event.key === "Delete" || event.key === "Backspace") {
                event.preventDefault();
                onDelete?.();
                return;
            }

            // Ctrl+A - Select all
            if (isCtrlOrCmd && event.key === "a") {
                event.preventDefault();
                onSelectAll?.();
                return;
            }

            // Ctrl+D - Duplicate (only for nodes)
            if (isCtrlOrCmd && event.key === "d") {
                event.preventDefault();
                if (canDuplicate) {
                    onDuplicate?.();
                }
                return;
            }

            // Ctrl+C - Copy (only for nodes)
            if (isCtrlOrCmd && event.key === "c") {
                event.preventDefault();
                if (canCopy) {
                    onCopy?.();
                }
                return;
            }

            // Ctrl+V - Paste
            if (isCtrlOrCmd && event.key === "v") {
                event.preventDefault();
                onPaste?.();
                return;
            }

            // Ctrl+Z - Undo
            if (isCtrlOrCmd && !event.shiftKey && event.key === "z") {
                event.preventDefault();
                onUndo?.();
                return;
            }

            // Ctrl+Shift+Z or Ctrl+Y - Redo
            if ((isCtrlOrCmd && event.shiftKey && event.key === "z") || (isCtrlOrCmd && event.key === "y")) {
                event.preventDefault();
                onRedo?.();
                return;
            }
        };

        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [onDelete, onSelectAll, onDuplicate, onCopy, onPaste, onUndo, onRedo, canDuplicate, canCopy]);
};
