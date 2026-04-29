"""
Cancellation controller for graph execution.

Provides thread-safe cancellation state management for individual nodes
and global execution interruption.
"""

from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from typing import Callable, Dict, List, Optional, Set, Tuple, Any


class CancellationController:
    """Thread-safe controller for managing cancellation state during graph execution.

    Supports:
    - Global cancellation (cancel_all): Stops entire execution
    - Per-node cancellation (cancel_node): Stops specific node and its dependents
    - Task registration: Tracks running asyncio tasks for forced cancellation
    - Process tracking: Tracks subprocesses for forced termination
    - Interruption callbacks: Notify listeners when interruption is requested
    - Loop-body tracking: When a loop is cancelled, its body nodes are also cancelled
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
        self._running_processes: Dict[str, List[subprocess.Popen]] = {}
        self._interruption_callbacks: List[Callable[[Optional[str]], None]] = []
        self._interruption_time: Optional[float] = None
        # Track loop -> body node relationships for cascading cancellation
        self._loop_body_nodes: Dict[str, Set[str]] = {}
        # Track body node -> parent loop for reverse lookup
        self._body_to_loop: Dict[str, str] = {}

    def reset(self) -> None:
        """Reset all cancellation state for a new execution run."""
        self._cancel_all.clear()
        self._interruption_time = None
        with self._state_lock:
            self._cancelled_nodes.clear()
            self._running_tasks = {}
            self._running_processes = {}
            self._loop_body_nodes = {}
            self._body_to_loop = {}

    def register_loop_body(self, loop_id: str, body_nodes: Set[str]) -> None:
        """Register loop-body relationships for cascading cancellation.

        When a loop node is cancelled, all its body nodes will also be cancelled.

        Args:
            loop_id: ID of the loop node
            body_nodes: Set of node IDs that are inside the loop body
        """
        with self._state_lock:
            self._loop_body_nodes[loop_id] = body_nodes
            for body_id in body_nodes:
                self._body_to_loop[body_id] = loop_id

    def cancel_all(self) -> None:
        """Request cancellation of entire execution."""
        self._cancel_all.set()
        self._interruption_time = time.time()
        self._cancel_running_processes()
        self.cancel_running_tasks()
        self._notify_interruption(None)

    def cancel_node(self, node_id: str) -> None:
        """Request cancellation of a specific node.

        If the node is a loop, all its body nodes are also cancelled.

        Args:
            node_id: ID of the node to cancel
        """
        with self._state_lock:
            self._cancelled_nodes.add(node_id)
            body_nodes = set(self._loop_body_nodes.get(node_id, set()))
            # If this is a loop node, cascade cancellation to all body nodes
            for body_id in body_nodes:
                self._cancelled_nodes.add(body_id)

        self._cancel_running_processes(target=node_id)
        self.cancel_running_tasks(target=node_id)

        for body_id in body_nodes:
            self._cancel_running_processes(target=body_id)
            self.cancel_running_tasks(target=body_id)

        self._notify_interruption(node_id)

    def should_stop(self) -> bool:
        """Check if global cancellation has been requested."""
        return self._cancel_all.is_set()

    def is_cancelled(self, node_id: Optional[str] = None) -> bool:
        """Check if execution should be cancelled.

        Args:
            node_id: Optional node ID to check for specific cancellation

        Returns:
            True if global cancellation is set, or if the specific node is cancelled,
            or if the node is inside a loop that has been cancelled.
        """
        if self._cancel_all.is_set():
            return True
        if node_id is not None:
            with self._state_lock:
                if node_id in self._cancelled_nodes:
                    return True
                # Also check if this node's parent loop is cancelled
                parent_loop = self._body_to_loop.get(node_id)
                if parent_loop and parent_loop in self._cancelled_nodes:
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

    def register_process(self, node_id: str, proc: subprocess.Popen) -> None:
        """Register a subprocess for potential termination.

        Args:
            node_id: ID of the node that spawned the process
            proc: The subprocess.Popen object
        """
        with self._state_lock:
            if node_id not in self._running_processes:
                self._running_processes[node_id] = []
            self._running_processes[node_id].append(proc)

    def clear_process(self, node_id: str, proc: Optional[subprocess.Popen] = None) -> None:
        """Remove a completed process from the registry.

        Args:
            node_id: ID of the node
            proc: Optional specific process to remove. If None, removes all for node.
        """
        with self._state_lock:
            if node_id not in self._running_processes:
                return
            if proc is None:
                self._running_processes.pop(node_id, None)
            else:
                self._running_processes[node_id] = [
                    p for p in self._running_processes[node_id] if p is not proc
                ]
                if not self._running_processes[node_id]:
                    del self._running_processes[node_id]

    def _cancel_running_processes(self, target: Optional[str] = None) -> None:
        """Terminate running subprocesses.

        Args:
            target: Optional node ID to terminate processes for. If None, terminates all.
        """
        with self._state_lock:
            items = list(self._running_processes.items())

        for node_id, procs in items:
            if target and node_id != target:
                continue
            for proc in procs:
                try:
                    if proc.poll() is None:  # Process still running
                        proc.terminate()
                        # Give it a moment to terminate gracefully
                        try:
                            proc.wait(timeout=0.5)
                        except subprocess.TimeoutExpired:
                            # Force kill if it doesn't terminate
                            proc.kill()
                except Exception:
                    pass  # Best effort - process may already be gone

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

    def add_interruption_callback(self, callback: Callable[[Optional[str]], None]) -> None:
        """Add a callback to be notified when interruption is requested.

        Args:
            callback: Function that takes optional node_id (None for global interruption)
        """
        self._interruption_callbacks.append(callback)

    def remove_interruption_callback(self, callback: Callable[[Optional[str]], None]) -> None:
        """Remove an interruption callback."""
        if callback in self._interruption_callbacks:
            self._interruption_callbacks.remove(callback)

    def _notify_interruption(self, node_id: Optional[str]) -> None:
        """Notify all registered callbacks about interruption."""
        for callback in self._interruption_callbacks:
            try:
                callback(node_id)
            except Exception:
                pass  # Don't let callback errors break interruption

    def get_running_task_count(self) -> int:
        """Get count of currently running tasks."""
        with self._state_lock:
            return sum(1 for fut in self._running_tasks.values() if not fut.done())

    def get_running_process_count(self) -> int:
        """Get count of currently running processes."""
        with self._state_lock:
            count = 0
            for procs in self._running_processes.values():
                for proc in procs:
                    if proc.poll() is None:
                        count += 1
            return count

    @property
    def interruption_time(self) -> Optional[float]:
        """Get the timestamp when interruption was requested."""
        return self._interruption_time


__all__ = ["CancellationController"]
