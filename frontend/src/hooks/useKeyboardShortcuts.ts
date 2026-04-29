import { useCallback, useEffect, useState } from "react";

interface UseKeyboardShortcutsOptions {
    onDelete?: () => void;
    onSelectAll?: () => void;
    onDuplicate?: () => void;
    onCopy?: () => void;
    onPaste?: () => void;
    onUndo?: () => void;
    onRedo?: () => void;
    onRunGraph?: () => void;
    onRunSelection?: () => void;
    onInterruptAll?: () => void;
    // Phase 3 §7.2 — Ctrl+K / Cmd+K opens the NodeSearchPalette.
    onOpenSearch?: () => void;
    canDuplicate?: boolean;
    canCopy?: boolean;
    canRunGraph?: boolean;
    canRunSelection?: boolean;
    canInterrupt?: boolean;
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
        onRunGraph,
        onRunSelection,
        onInterruptAll,
        onOpenSearch,
        canDuplicate = true,
        canCopy = true,
        canRunGraph = true,
        canRunSelection = true,
        canInterrupt = true,
    } = options;

    useEffect(() => {
        const handleKeyDown = (event: KeyboardEvent) => {
            const target = event.target as HTMLElement;
            const isCtrlOrCmd = event.ctrlKey || event.metaKey;

            // Phase 3 §7.2 — Ctrl+K / Cmd+K *always* opens the search
            // palette, even from inside a text input. Mirrors how
            // VSCode / Linear / Notion handle their command palettes.
            if (isCtrlOrCmd && event.key.toLowerCase() === "k") {
                event.preventDefault();
                onOpenSearch?.();
                return;
            }

            // Don't trigger other shortcuts when typing.
            if (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.tagName === "SELECT" || target.isContentEditable) {
                return;
            }

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

            // Ctrl+Enter - Run graph, Ctrl+Shift+Enter - Run selection
            if (isCtrlOrCmd && event.key === "Enter") {
                event.preventDefault();
                if (event.shiftKey) {
                    if (canRunSelection) {
                        onRunSelection?.();
                    }
                } else if (canRunGraph) {
                    onRunGraph?.();
                }
                return;
            }

            // Escape - Interrupt all
            if (event.key === "Escape") {
                if (canInterrupt) {
                    event.preventDefault();
                    onInterruptAll?.();
                }
                return;
            }
        };

        document.addEventListener("keydown", handleKeyDown);
        return () => document.removeEventListener("keydown", handleKeyDown);
    }, [
        onDelete,
        onSelectAll,
        onDuplicate,
        onCopy,
        onPaste,
        onUndo,
        onRedo,
        onRunGraph,
        onRunSelection,
        onInterruptAll,
        onOpenSearch,
        canDuplicate,
        canCopy,
        canRunGraph,
        canRunSelection,
        canInterrupt,
    ]);
};
