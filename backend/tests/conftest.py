"""
Pytest configuration and fixtures for LiGuard-Web backend tests.
"""

from __future__ import annotations

import pytest
from typing import Any, Dict, List


@pytest.fixture
def simple_graph() -> Dict[str, Any]:
    """A minimal graph with two constant nodes and an addition node."""
    return {
        "nodes": [
            {
                "id": "const-a",
                "type": "core.literal.int",
                "input_values": {"value": 5},
            },
            {
                "id": "const-b",
                "type": "core.literal.int",
                "input_values": {"value": 3},
            },
            {
                "id": "add",
                "type": "core.math.add",
            },
        ],
        "links": [
            {
                "from_node": "const-a",
                "from_port": "value",
                "to_node": "add",
                "to_port": "a",
            },
            {
                "from_node": "const-b",
                "from_port": "value",
                "to_node": "add",
                "to_port": "b",
            },
        ],
        "output_nodes": [
            {"node_id": "add", "port": "sum", "alias": "sum"},
        ],
    }


@pytest.fixture
def loop_graph() -> Dict[str, Any]:
    """A graph with a for loop (0..2)."""
    return {
        "nodes": [
            {
                "id": "last",
                "type": "core.literal.int",
                "input_values": {"value": 2},
            },
            {
                "id": "loop",
                "type": "core.control.for",
            },
            {
                "id": "inside-loop",
                "type": "core.debug.log",
            },
        ],
        "links": [
            {
                "from_node": "last",
                "from_port": "value",
                "to_node": "loop",
                "to_port": "last_index",
            },
            {
                "from_node": "loop",
                "from_port": "loop_body",
                "to_node": "inside-loop",
                "to_port": "control_in",
                "kind": "control",
            },
        ],
    }


@pytest.fixture
def ifelse_graph() -> Dict[str, Any]:
    """A graph with an if/else branch."""
    return {
        "nodes": [
            {
                "id": "condition",
                "type": "core.literal.boolean",
                "input_values": {"value": True},
            },
            {
                "id": "branch",
                "type": "core.control.ifelse",
            },
            {
                "id": "true-path",
                "type": "core.debug.log",
            },
            {
                "id": "false-path",
                "type": "core.debug.log",
            },
        ],
        "links": [
            {
                "from_node": "condition",
                "from_port": "value",
                "to_node": "branch",
                "to_port": "condition",
            },
            {
                "from_node": "branch",
                "from_port": "true",
                "to_node": "true-path",
                "to_port": "control_in",
                "kind": "control",
            },
            {
                "from_node": "branch",
                "from_port": "false",
                "to_node": "false-path",
                "to_port": "control_in",
                "kind": "control",
            },
        ],
    }
