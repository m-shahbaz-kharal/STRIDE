"""
Typed exception hierarchy for STRIDE node execution.

This module defines the error classes that nodes raise to signal different
failure modes. The execution engine inspects the exception type and propagates
the structured ``code``/``port``/``details`` payload to the frontend so the UI
can render category-specific badges and disclosure tooltips.

Phase 0 note
------------
This file is **scaffolding only** — it is intentionally not yet imported by
``backend/app/executor/node_execution.py``. The dispatch site is rewritten in
Phase 2 (see ``docs/architecture/unified-type-system-and-ux.md`` §10 Phase 2).
Adding the file in Phase 0 lets later phases land additively without churn.

The class hierarchy is the canonical one specified in
``docs/architecture/unified-type-system-and-ux.md`` §5.2.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class NodeError(Exception):
    """Base class for typed node errors.

    All structured errors raised by node ``forward()`` implementations should
    derive from this class. The execution engine catches ``NodeError`` and
    serialises ``code``/``port``/``details``/``node_id`` into the WS event
    payload (§6.3 of the design doc).

    Attributes
    ----------
    code:
        Stable machine-readable error code, e.g. ``"node_input_error"``. The
        frontend uses this to look up the category icon and label.
    message:
        Human-readable message — same as ``str(self)``. Stored on the instance
        for symmetry with ``code``/``details`` so ``error.message`` is always
        available without going through ``args``.
    details:
        Free-form structured payload (got/expected values, port shapes, etc.).
    port:
        Optional offending port name, when the error is attributable to a
        single input. Distinct from ``node_id`` — ``port`` identifies *which
        input on this node* failed, ``node_id`` identifies *which node*.
    node_id:
        Optional node id. Normally filled in by the execution engine when it
        catches the exception (the node itself does not know its own runtime
        id when it raises). Nodes that already know their id may set it.
    """

    code: str = "node_error"

    def __init__(
        self,
        message: str,
        *,
        port: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        node_id: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message: str = message
        self.port: Optional[str] = port
        self.details: Dict[str, Any] = details or {}
        self.node_id: Optional[str] = node_id

    def to_payload(self) -> Dict[str, Any]:
        """Render this error as a JSON-serialisable dict.

        Used by the execution engine when emitting structured error events.
        Phase 0 is the only consumer-free place this lives — Phase 2 hooks it
        up in ``backend/app/executor/node_execution.py``.
        """
        return {
            "code": self.code,
            "message": self.message,
            "port": self.port,
            "details": dict(self.details),
            "node_id": self.node_id,
        }


class NodeInputError(NodeError):
    """Input value violates the node's expectations.

    Use when a value is the right type but wrong shape/range/contents:

        raise NodeInputError(
            "voxel_size must be > 0",
            port="voxel_size",
            details={"got": -0.5, "min": 0.0},
        )
    """

    code = "node_input_error"


class NodeTypeError(NodeError):
    """A typed input was the wrong category.

    Should rarely fire — graph validation catches this — but stateful nodes
    that cast at runtime (e.g. ``if isinstance(x, StreamResource)``) can use
    it.
    """

    code = "node_type_error"


class NodeRuntimeError(NodeError):
    """A runtime failure during forward (GPU OOM, division by zero, file IO
    error, etc.). Wrap the underlying exception.
    """

    code = "node_runtime_error"


class NodeMissingDependencyError(NodeError):
    """A required Python package or external binary is missing."""

    code = "node_missing_dependency"


class NodeCancelled(NodeError):
    """Cooperative cancellation marker.

    Raised by ``ctx.check_cancelled()`` helpers when the node decides to
    abort. The execution engine special-cases this code so cancellation is
    not reported as an error in the UI.
    """

    code = "node_cancelled"


class NodeFileNotFoundError(NodeError):
    """A file the node was asked to read does not exist."""

    code = "node_file_not_found"


class NodeNetworkError(NodeError):
    """A network operation (HTTP, RTSP, websocket, etc.) failed."""

    code = "node_network_error"


__all__ = [
    "NodeError",
    "NodeInputError",
    "NodeTypeError",
    "NodeRuntimeError",
    "NodeMissingDependencyError",
    "NodeCancelled",
    "NodeFileNotFoundError",
    "NodeNetworkError",
]
