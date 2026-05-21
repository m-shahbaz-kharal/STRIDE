from __future__ import annotations

import hashlib
import json
import os
import threading
from collections import OrderedDict
from dataclasses import dataclass, field, asdict, is_dataclass
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
    display_name: Optional[str] = None  # Human-readable node name for UI
    outputs: Dict[str, Any] = field(default_factory=dict)
    logs: List[str] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0
    duration_ms: float = 0.0
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None  # Full stacktrace for debugging
    error_payload: Optional[Dict[str, Any]] = None  # Structured NodeError payload (Phase 2 §6.3)
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
    display_name: Optional[str] = None  # Human-readable node name for UI
    status: Optional[NodeStatus] = None
    outputs: Optional[Dict[str, Any]] = None
    logs: Optional[List[str]] = None
    duration_ms: Optional[float] = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    error_details: Optional[str] = None  # Full stacktrace for debugging
    error_payload: Optional[Dict[str, Any]] = None  # Structured NodeError payload (Phase 2 §6.3)
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
    """Thread-safe LRU cache shared across executor instances.

    The cache is process-global so repeated runs of the same graph can
    skip redundant work. To keep memory bounded across long-running
    deployments, entries are evicted in least-recently-used order once
    ``MAX_ENTRIES`` is reached. Configure via ``STRIDE_CACHE_MAX_ENTRIES``.
    """

    MAX_ENTRIES: int = int(os.getenv("STRIDE_CACHE_MAX_ENTRIES", "1024"))

    _cache: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()
    _metadata: Dict[str, Any] = {}
    _lock = threading.Lock()

    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    @staticmethod
    def _hash_bytes(data: bytes) -> Dict[str, Any]:
        return {
            "__bytes__": hashlib.sha256(data).hexdigest(),
            "len": len(data),
        }

    @classmethod
    def _normalize_for_key(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return cls._hash_bytes(value)
        if isinstance(value, bytearray):
            return cls._hash_bytes(bytes(value))
        if isinstance(value, memoryview):
            return cls._hash_bytes(value.tobytes())
        if isinstance(value, dict):
            return {
                str(key): cls._normalize_for_key(val)
                for key, val in sorted(value.items(), key=lambda item: str(item[0]))
            }
        if isinstance(value, (list, tuple)):
            return [cls._normalize_for_key(item) for item in value]
        if isinstance(value, set):
            normalized = [cls._normalize_for_key(item) for item in value]
            return sorted(
                normalized,
                key=lambda item: json.dumps(item, sort_keys=True, default=str),
            )
        if is_dataclass(value):
            return cls._normalize_for_key(asdict(value))

        try:
            import numpy as np  # type: ignore

            if isinstance(value, np.ndarray):
                return {
                    "__ndarray__": cls._hash_bytes(value.tobytes())["__bytes__"],
                    "dtype": str(value.dtype),
                    "shape": list(value.shape),
                }
            if isinstance(value, np.generic):
                return value.item()
        except Exception:
            pass

        try:
            import torch  # type: ignore

            if isinstance(value, torch.Tensor):
                cpu_tensor = value.detach().cpu()
                return {
                    "__tensor__": cls._hash_bytes(cpu_tensor.numpy().tobytes())["__bytes__"],
                    "dtype": str(cpu_tensor.dtype),
                    "shape": list(cpu_tensor.shape),
                }
        except Exception:
            pass

        try:
            from PIL import Image  # type: ignore

            if isinstance(value, Image.Image):
                return {
                    "__image__": cls._hash_bytes(value.tobytes())["__bytes__"],
                    "mode": value.mode,
                    "size": list(value.size),
                }
        except Exception:
            pass

        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            try:
                return cls._normalize_for_key(to_dict())
            except Exception:
                pass

        if hasattr(value, "__dict__"):
            shallow: Dict[str, Any] = {}
            for key, val in vars(value).items():
                if val is None or isinstance(val, (str, int, float, bool)):
                    shallow[key] = val
            if shallow:
                return {
                    "__object__": value.__class__.__name__,
                    "fields": shallow,
                }

        return {"__repr__": repr(value)}

    @staticmethod
    def _compute_key(node_type: str, params: Dict[str, Any], inputs: Dict[str, Any]) -> str:
        """Create a stable hash from node metadata and inputs.

        Uses the full 256-bit SHA-256 digest (64 hex chars). The previous
        16-char truncation was at risk of birthday collisions once the
        cache held more than ~4 billion entries; keeping the full digest
        is cheap and eliminates the concern entirely.
        """
        key_data = {
            "type": node_type,
            "params": ExecutionCache._normalize_for_key(params),
            "inputs": ExecutionCache._normalize_for_key(inputs),
        }
        key_str = json.dumps(key_data, sort_keys=True, default=str)
        return hashlib.sha256(key_str.encode()).hexdigest()

    def get(self, node_type: str, params: Dict[str, Any], inputs: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        cache_key = self._compute_key(node_type, params, inputs)
        with self._lock:
            if cache_key not in self._cache:
                return None
            # Touch for LRU recency.
            self._cache.move_to_end(cache_key)
            return self._cache[cache_key]

    def set(
        self,
        node_type: str,
        params: Dict[str, Any],
        inputs: Dict[str, Any],
        outputs: Dict[str, Any],
        node_id: Optional[str] = None,
    ) -> None:
        if not self.enabled:
            return
        cache_key = self._compute_key(node_type, params, inputs)
        node_id_value = node_id
        if node_id_value is None and isinstance(params, dict):
            raw_id = params.get("__cache_node_id")
            if raw_id is not None:
                node_id_value = str(raw_id)
        with self._lock:
            self._cache[cache_key] = outputs
            self._cache.move_to_end(cache_key)
            self._metadata[cache_key] = {"node_type": node_type, "node_id": node_id_value}
            # LRU eviction. ``popitem(last=False)`` drops the oldest entry.
            while len(self._cache) > self.MAX_ENTRIES:
                old_key, _ = self._cache.popitem(last=False)
                self._metadata.pop(old_key, None)

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
            keys_to_remove = []
            for key, meta in cls._metadata.items():
                cached_type = meta if isinstance(meta, str) else meta.get("node_type")
                if cached_type == node_type:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                cls._cache.pop(key, None)
                cls._metadata.pop(key, None)
            return len(keys_to_remove)

    @classmethod
    def clear_by_node(cls, node_id: str) -> int:
        with cls._lock:
            keys_to_remove = []
            for key, meta in cls._metadata.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("node_id") == node_id:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                cls._cache.pop(key, None)
                cls._metadata.pop(key, None)
            return len(keys_to_remove)

    @classmethod
    def clear_by_nodes(cls, node_ids: List[str]) -> int:
        node_id_set = {str(node_id) for node_id in node_ids}
        if not node_id_set:
            return 0
        with cls._lock:
            keys_to_remove = []
            for key, meta in cls._metadata.items():
                if not isinstance(meta, dict):
                    continue
                if meta.get("node_id") in node_id_set:
                    keys_to_remove.append(key)
            for key in keys_to_remove:
                cls._cache.pop(key, None)
                cls._metadata.pop(key, None)
            return len(keys_to_remove)

    @classmethod
    def size(cls) -> int:
        with cls._lock:
            return len(cls._cache)
