from __future__ import annotations

import hashlib
import json
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class GraphExecutionError(Exception):
    """Raised when the graph configuration is invalid or cannot be executed."""

    def __init__(self, message: str, code: str = "execution_error", details: Optional[Dict[str, Any]] = None) -> None:  # type: ignore[name-defined]
        super().__init__(message)
        self.code = code
        self.details = details or {}


class NodeStatus(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    ERROR = "error"


@dataclass
class Link:
    from_node: str
    from_port: str
    to_node: str
    to_port: str
    kind: str = "data"  # "data" or "control"


@dataclass
class NodeExecutionResult:
    """Result of executing a single node."""

    node_id: str
    node_type: str
    status: NodeStatus
    outputs: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None
    level: int = 0  # Topological level for parallel execution
    from_cache: bool = False  # Whether result came from cache
    branch_id: Optional[str] = None  # Branch this node belongs to (hybrid execution)
    is_merge_point: bool = False  # Whether this node receives inputs from multiple branches


@dataclass
class ExecutionEvent:
    """Event emitted during graph execution for real-time updates."""

    event_type: str  # "start", "node_queued", "node_started", "node_completed", "node_skipped", "node_error", "complete"
    execution_id: str
    timestamp: float
    node_id: Optional[str] = None
    node_type: Optional[str] = None
    status: Optional[NodeStatus] = None
    outputs: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    level: Optional[int] = None
    progress: Optional[float] = None  # 0.0 to 1.0
    total_nodes: Optional[int] = None
    completed_nodes: Optional[int] = None
    from_cache: Optional[bool] = None  # Whether result came from cache
    # Execution plan info (sent at start)
    execution_plan: Optional[List[Dict[str, Any]]] = None
    levels: Optional[List[List[str]]] = None
    # Branch info for hybrid execution model
    branch_id: Optional[str] = None
    is_merge_point: Optional[bool] = None
    branches: Optional[Dict[str, List[str]]] = None  # branch_id -> node_ids (sent at start)
    merge_points: Optional[List[str]] = None  # List of merge point node_ids (sent at start)


@dataclass
class ExecutionStats:
    """Statistics about graph execution."""

    total_nodes: int = 0
    executed_nodes: int = 0
    skipped_nodes: int = 0
    cached_nodes: int = 0  # Nodes that used cached results
    error_nodes: int = 0
    total_time_ms: float = 0.0
    node_time_ms: float = 0.0  # Sum of individual node times
    parallel_efficiency: float = 0.0  # node_time_ms / total_time_ms (higher = more parallelism)
    max_parallelism: int = 0  # Max nodes that ran in parallel
    levels_executed: int = 0


class ExecutionCache:
    """Thread-safe cache shared across executor instances."""

    _cache: Dict[str, Dict[str, Any]] = {}
    _metadata: Dict[str, str] = {}
    _lock = threading.Lock()

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    @staticmethod
    def _compute_key(node_type: str, params: Dict[str, Any], inputs: Dict[str, Any]) -> str:
        """Create a stable hash from node metadata and inputs."""
        key_data = {
            "type": node_type,
            "params": params,
            "inputs": inputs,
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(key_str.encode()).hexdigest()[:16]

    def get(self, node_type: str, params: Dict[str, Any], inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        cache_key = self._compute_key(node_type, params, inputs)
        with self._lock:
            return self._cache.get(cache_key)

    def set(self, node_type: str, params: Dict[str, Any], inputs: Dict[str, Any], outputs: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        cache_key = self._compute_key(node_type, params, inputs)
        with self._lock:
            self._cache[cache_key] = outputs
            self._metadata[cache_key] = node_type

    @classmethod
    def clear_all(cls) -> int:
        with cls._lock:
            count = len(cls._cache)
            cls._cache.clear()
            cls._metadata.clear()
            return count

    @classmethod
    def clear_by_type(cls, node_type: str) -> int:
        with cls._lock:
            keys_to_remove = [key for key, cached_type in cls._metadata.items() if cached_type == node_type]
            for key in keys_to_remove:
                cls._cache.pop(key, None)
                cls._metadata.pop(key, None)
            return len(keys_to_remove)

    @classmethod
    def size(cls) -> int:
        with cls._lock:
            return len(cls._cache)
