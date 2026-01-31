"""
Executor package for LiGuard-Web graph execution.

This package provides the core execution engine for running node graphs.

Module organization:
- cancellation: Thread-safe cancellation controller
- graph_builder: Builds graph structure from definition
- control_flow: Loop, if/else, and branch detection
- node_execution: Individual node execution with caching
- scheduler: Ready-queue scheduling for parallel execution
- events: Execution event creation and emission
- completion: Task completion and failure propagation
- streaming: Main streaming executor orchestrator
- utils: Shared utility functions
"""

from __future__ import annotations

# Export cancellation controller for direct use
from .cancellation import CancellationController
from .graph_builder import GraphBuilder
from .control_flow import LoopHandler, IfElseHandler, BranchHandler
from .node_execution import NodeExecutor
from .scheduler import ReadyQueueScheduler, LoopIterationScheduler
from .events import ExecutionEventEmitter
from .completion import TaskCompletionHandler, LoopCompletionHandler
from .streaming import StreamingExecutor
from .utils import (
    normalize_type,
    collect_dependents,
    expand_dependencies,
    collect_downstream,
    collect_outputs,
    calculate_stats,
)


def __getattr__(name: str):
    """Lazy import to avoid circular dependencies."""
    if name == "GraphExecutor":
        from ..runner import GraphExecutor
        return GraphExecutor
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "GraphExecutor",
    "CancellationController",
    "GraphBuilder",
    "LoopHandler",
    "IfElseHandler",
    "BranchHandler",
    "NodeExecutor",
    "ReadyQueueScheduler",
    "LoopIterationScheduler",
    "ExecutionEventEmitter",
    "TaskCompletionHandler",
    "LoopCompletionHandler",
    "StreamingExecutor",
    "normalize_type",
    "collect_dependents",
    "expand_dependencies",
    "collect_downstream",
    "collect_outputs",
    "calculate_stats",
]
