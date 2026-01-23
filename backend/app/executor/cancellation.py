"""
Cancellation controller for graph execution.

Provides thread-safe cancellation state management for individual nodes
and global execution interruption.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Dict, Optional, Set


class CancellationController:
    """Thread-safe controller for managing cancellation state during graph execution.
    
    Supports:
    - Global cancellation (cancel_all): Stops entire execution
    - Per-node cancellation (cancel_node): Stops specific node and its dependents
    - Task registration: Tracks running asyncio tasks for forced cancellation
    """

    def __init__(self, state_lock: threading.Lock) -> None:
        """Initialize the cancellation controller.
        
        Args:
            state_lock: Shared lock for thread-safe state access
        """
        self._state_lock = state_lock
        self._cancel_all = threading.Event()
        self._cancelled_nodes: Set[str] = set()
        self._running_tasks: Dict[str, asyncio.Future] = {}

    def reset(self) -> None:
        """Reset all cancellation state for a new execution run."""
        self._cancel_all.clear()
        self._cancelled_nodes.clear()
        with self._state_lock:
            self._running_tasks = {}

    def cancel_all(self) -> None:
        """Request cancellation of entire execution."""
        self._cancel_all.set()
        self.cancel_running_tasks()

    def cancel_node(self, node_id: str) -> None:
        """Request cancellation of a specific node.
        
        Args:
            node_id: ID of the node to cancel
        """
        self._cancelled_nodes.add(node_id)
        self.cancel_running_tasks(target=node_id)

    def should_stop(self) -> bool:
        """Check if global cancellation has been requested."""
        return self._cancel_all.is_set()

    def is_cancelled(self, node_id: Optional[str] = None) -> bool:
        """Check if execution should be cancelled.
        
        Args:
            node_id: Optional node ID to check for specific cancellation
            
        Returns:
            True if global cancellation is set, or if the specific node is cancelled
        """
        if self._cancel_all.is_set():
            return True
        if node_id is not None and node_id in self._cancelled_nodes:
            return True
        return False

    def register_running(self, node_id: str, fut: asyncio.Future) -> None:
        """Register a running task for potential cancellation.
        
        Args:
            node_id: ID of the node being executed
            fut: The asyncio Future representing the task
        """
        with self._state_lock:
            self._running_tasks[node_id] = fut

    def clear_running(self, node_id: str) -> None:
        """Remove a completed task from the running registry.
        
        Args:
            node_id: ID of the completed node
        """
        with self._state_lock:
            self._running_tasks.pop(node_id, None)

    def cancel_running_tasks(self, target: Optional[str] = None) -> None:
        """Cancel running asyncio tasks.
        
        Args:
            target: Optional node ID to cancel specifically. If None, cancels all tasks.
        """
        with self._state_lock:
            items = list(self._running_tasks.items())
        for node_id, fut in items:
            if target and node_id != target:
                continue
            if not fut.done():
                fut.cancel()


__all__ = ["CancellationController"]
