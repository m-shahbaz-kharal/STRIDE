from __future__ import annotations

import asyncio
import random

from .execution import GraphExecutionError
from .runner import GraphExecutor


def assert_eq(label: str, got: object, expected: object) -> None:
    if got != expected:
        raise AssertionError(f"{label} expected {expected!r}, got {got!r}")


def run_graph(name: str, graph: dict, expected_outputs: dict | None = None, options: dict | None = None) -> dict:
    result = GraphExecutor(graph, options=options).run()
    outputs = result["outputs"]
    if expected_outputs:
        for key, expected in expected_outputs.items():
            assert_eq(f"{name}:{key}", outputs.get(key), expected)
    print(f"{name}: PASS outputs={outputs}")
    return result


def assert_trace_order(result: dict, before_id: str, after_id: str) -> None:
    trace = result.get("trace", [])
    ids = [entry.get("node_id") for entry in trace]
    if before_id not in ids or after_id not in ids:
        raise AssertionError(f"Trace missing expected nodes: {before_id}, {after_id}")
    if ids.index(before_id) > ids.index(after_id):
        raise AssertionError(f"Expected {before_id} before {after_id}, got {ids}")


def assert_node_event_order(events: list[dict], node_id: str) -> None:
    first = next((i for i, e in enumerate(events) if e.get("node_id") == node_id), None)
    if first is None:
        raise AssertionError(f"expected events for node {node_id}")
    node_events = [e["type"] for e in events if e.get("node_id") == node_id]
    if "node_started" in node_events and "node_completed" in node_events:
        if node_events.index("node_started") > node_events.index("node_completed"):
            raise AssertionError(f"node {node_id} completed before it started")


def assert_raises(name: str, graph: dict, expected_code: str | None = None) -> None:
    try:
        GraphExecutor(graph).run()
    except GraphExecutionError as exc:
        if expected_code and exc.code != expected_code:
            raise AssertionError(f"{name} expected code {expected_code}, got {exc.code}") from exc
        print(f"{name}: PASS error={exc.code}")
        return
    raise AssertionError(f"{name} expected GraphExecutionError")


def has_cached_logs(result: dict) -> bool:
    for entry in result.get("trace", []):
        for log in entry.get("logs") or []:
            if "[CACHED]" in log:
                return True
    return False


def has_cached_logs_for_node(result: dict, node_id: str) -> bool:
    for entry in result.get("trace", []):
        if entry.get("node_id") != node_id:
            continue
        for log in entry.get("logs") or []:
            if "[CACHED]" in log:
                return True
    return False


def assert_progress_complete(events: list[dict]) -> None:
    complete = next((e for e in events if e.get("type") == "complete"), None)
    if not complete:
        raise AssertionError("expected complete event")
    if complete.get("progress") not in (1.0, 1):
        raise AssertionError(f"expected progress=1.0, got {complete.get('progress')}")


def assert_progress_monotonic(events: list[dict]) -> None:
    last = -1.0
    for event in events:
        value = event.get("progress")
        if value is None:
            continue
        if value < last:
            raise AssertionError(f"progress decreased from {last} to {value}")
        last = value


def test_simple_add() -> None:
    run_graph(
        "simple_add",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 12}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 7}},
                {"id": "add", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        },
        {"sum": 19.0},
    )


def test_string_add() -> None:
    run_graph(
        "string_add",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.string", "params": {"value": "hello"}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 5}},
                {"id": "add", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        },
        {"sum": "hello5"},
    )


def test_make_array() -> None:
    run_graph(
        "make_array",
        {
            "nodes": [
                {"id": "i0", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "i1", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "i2", "type": "core.literal.string", "params": {"value": "x"}},
                {
                    "id": "arr",
                    "type": "core.container.make_array",
                    "input_ports_override": ["control_in", "item_0", "item_1", "item_2"],
                    "input_port_types_override": {
                        "control_in": {"kind": "control"},
                        "item_0": {"kind": "any"},
                        "item_1": {"kind": "any"},
                        "item_2": {"kind": "any"},
                    },
                    "params": {},
                },
            ],
            "links": [
                {"from_node": "i0", "from_port": "value", "to_node": "arr", "to_port": "item_0"},
                {"from_node": "i1", "from_port": "value", "to_node": "arr", "to_port": "item_1"},
                {"from_node": "i2", "from_port": "value", "to_node": "arr", "to_port": "item_2"},
            ],
            "output_nodes": [{"node_id": "arr", "port": "array", "alias": "array"}],
        },
        {"array": [1, 2, "x"]},
    )


def test_for_loop_sum() -> None:
    run_graph(
        "for_loop_sum",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "first", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "last", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "loop", "type": "core.control.for", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "first", "from_port": "value", "to_node": "loop", "to_port": "first_index"},
                {"from_node": "last", "from_port": "value", "to_node": "loop", "to_port": "last_index"},
                {"from_node": "loop", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 6.0},
    )


def test_while_loop_sum() -> None:
    run_graph(
        "while_loop_sum",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "cond", "type": "core.literal.boolean", "params": {"value": True}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "loop", "type": "core.control.while", "params": {"max_iterations": 3}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "cond", "from_port": "value", "to_node": "loop", "to_port": "condition"},
                {"from_node": "loop", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 3.0},
    )


def test_control_ordering() -> None:
    result = run_graph(
        "control_ordering",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "value", "type": "core.literal.int", "params": {"value": 42}},
                {"id": "set", "type": "core.var.set", "params": {"name": "x"}},
                {"id": "get", "type": "core.var.get", "params": {"name": "x", "default": 0}},
            ],
            "links": [
                {"from_node": "value", "from_port": "value", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "set", "from_port": "control_out", "to_node": "get", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get", "port": "value", "alias": "value"}],
        },
        {"value": 42},
    )
    assert_trace_order(result, "set", "get")


def test_loop_completed_uses_last_index() -> None:
    run_graph(
        "loop_completed_last_index",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "first", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "last", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "loop", "type": "core.control.for", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "last_index"}},
                {"id": "get", "type": "core.var.get", "params": {"name": "last_index", "default": -1}},
            ],
            "links": [
                {"from_node": "first", "from_port": "value", "to_node": "loop", "to_port": "first_index"},
                {"from_node": "last", "from_port": "value", "to_node": "loop", "to_port": "last_index"},
                {"from_node": "loop", "from_port": "index", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "set", "from_port": "control_out", "to_node": "get", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get", "port": "value", "alias": "last_index"}],
        },
        {"last_index": 3},
    )


def test_repeat_loop_sum() -> None:
    run_graph(
        "repeat_loop_sum",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "count", "type": "core.literal.int", "params": {"value": 4}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "loop", "type": "core.control.repeat", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "one", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "count", "from_port": "value", "to_node": "loop", "to_port": "count"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "one", "from_port": "value", "to_node": "add", "to_port": "b"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 4.0},
    )


def test_reverse_for_loop_sum() -> None:
    run_graph(
        "reverse_for_loop_sum",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "first", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "last", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "loop", "type": "core.control.for", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "first", "from_port": "value", "to_node": "loop", "to_port": "first_index"},
                {"from_node": "last", "from_port": "value", "to_node": "loop", "to_port": "last_index"},
                {"from_node": "loop", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 6.0},
    )


def test_while_loop_no_iterations() -> None:
    run_graph(
        "while_loop_no_iterations",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "cond", "type": "core.literal.boolean", "params": {"value": False}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "loop", "type": "core.control.while", "params": {"max_iterations": 5}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "one", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "cond", "from_port": "value", "to_node": "loop", "to_port": "condition"},
                {"from_node": "one", "from_port": "value", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "value"}],
        },
        {"value": 0},
    )


def test_nested_loops_increment() -> None:
    run_graph(
        "nested_loops_increment",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "outer_first", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "outer_last", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "inner_count", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "outer", "type": "core.control.for", "params": {}},
                {"id": "inner", "type": "core.control.repeat", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "one", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "outer_first", "from_port": "value", "to_node": "outer", "to_port": "first_index"},
                {"from_node": "outer_last", "from_port": "value", "to_node": "outer", "to_port": "last_index"},
                {"from_node": "inner_count", "from_port": "value", "to_node": "inner", "to_port": "count"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "one", "from_port": "value", "to_node": "add", "to_port": "b"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "outer", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "loop_body", "to_node": "inner", "to_port": "control_in", "kind": "control"},
                {"from_node": "inner", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 4.0},
    )


def test_logic_compare_and_boolean_ops() -> None:
    run_graph(
        "logic_compare_and_boolean_ops",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 5}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "cmp", "type": "core.logic.compare", "params": {"op": ">"}},
                {"id": "true", "type": "core.literal.boolean", "params": {"value": True}},
                {"id": "and", "type": "core.logic.and", "params": {}},
                {"id": "not", "type": "core.logic.not", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "cmp", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "cmp", "to_port": "b"},
                {"from_node": "cmp", "from_port": "result", "to_node": "and", "to_port": "a"},
                {"from_node": "true", "from_port": "value", "to_node": "and", "to_port": "b"},
                {"from_node": "and", "from_port": "result", "to_node": "not", "to_port": "value"},
            ],
            "output_nodes": [{"node_id": "not", "port": "result", "alias": "result"}],
        },
        {"result": False},
    )


def test_string_concat() -> None:
    run_graph(
        "string_concat",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.string", "params": {"value": "foo"}},
                {"id": "b", "type": "core.literal.string", "params": {"value": "bar"}},
                {"id": "concat", "type": "core.string.concat", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "concat", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "concat", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "concat", "port": "result", "alias": "result"}],
        },
        {"result": "foobar"},
    )


def test_casting_nodes() -> None:
    run_graph(
        "casting_nodes",
        {
            "nodes": [
                {"id": "str", "type": "core.literal.string", "params": {"value": "42"}},
                {"id": "flt", "type": "core.literal.string", "params": {"value": "3.5"}},
                {"id": "num", "type": "core.literal.int", "params": {"value": 10}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "to_int", "type": "core.cast.to_int", "params": {}},
                {"id": "to_float", "type": "core.cast.to_float", "params": {}},
                {"id": "to_string", "type": "core.cast.to_string", "params": {}},
                {"id": "to_boolean", "type": "core.cast.to_boolean", "params": {}},
            ],
            "links": [
                {"from_node": "str", "from_port": "value", "to_node": "to_int", "to_port": "value"},
                {"from_node": "flt", "from_port": "value", "to_node": "to_float", "to_port": "value"},
                {"from_node": "num", "from_port": "value", "to_node": "to_string", "to_port": "value"},
                {"from_node": "zero", "from_port": "value", "to_node": "to_boolean", "to_port": "value"},
            ],
            "output_nodes": [
                {"node_id": "to_int", "port": "value", "alias": "int_value"},
                {"node_id": "to_float", "port": "value", "alias": "float_value"},
                {"node_id": "to_string", "port": "value", "alias": "string_value"},
                {"node_id": "to_boolean", "port": "value", "alias": "bool_value"},
            ],
        },
        {"int_value": 42, "float_value": 3.5, "string_value": "10", "bool_value": False},
    )


def test_math_ops() -> None:
    run_graph(
        "math_ops",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.string", "params": {"value": "2"}},
                {"id": "b", "type": "core.literal.string", "params": {"value": "3.5"}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "neg", "type": "core.literal.string", "params": {"value": "-5"}},
                {"id": "mul", "type": "core.math.multiply", "params": {}},
                {"id": "div", "type": "core.math.divide", "params": {}},
                {"id": "pow", "type": "core.math.power", "params": {}},
                {"id": "abs", "type": "core.math.abs", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "mul", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "mul", "to_port": "b"},
                {"from_node": "a", "from_port": "value", "to_node": "div", "to_port": "a"},
                {"from_node": "zero", "from_port": "value", "to_node": "div", "to_port": "b"},
                {"from_node": "a", "from_port": "value", "to_node": "pow", "to_port": "base"},
                {"from_node": "b", "from_port": "value", "to_node": "pow", "to_port": "exponent"},
                {"from_node": "neg", "from_port": "value", "to_node": "abs", "to_port": "value"},
            ],
            "output_nodes": [
                {"node_id": "mul", "port": "product", "alias": "product"},
                {"node_id": "div", "port": "quotient", "alias": "quotient"},
                {"node_id": "pow", "port": "result", "alias": "result"},
                {"node_id": "abs", "port": "result", "alias": "abs"},
            ],
        },
        {"product": 7.0, "quotient": 0, "result": 11.313708498984761, "abs": 5.0},
    )


def test_container_nodes() -> None:
    run_graph(
        "container_nodes",
        {
            "nodes": [
                {"id": "start", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "end", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "range", "type": "core.container.range", "params": {}},
                {"id": "append_value", "type": "core.literal.int", "params": {"value": 4}},
                {"id": "append", "type": "core.container.append", "params": {}},
                {"id": "get", "type": "core.container.get_index", "params": {}},
                {"id": "length", "type": "core.container.length", "params": {}},
            ],
            "links": [
                {"from_node": "start", "from_port": "value", "to_node": "range", "to_port": "start"},
                {"from_node": "end", "from_port": "value", "to_node": "range", "to_port": "end"},
                {"from_node": "range", "from_port": "array", "to_node": "append", "to_port": "array"},
                {"from_node": "append_value", "from_port": "value", "to_node": "append", "to_port": "value"},
                {"from_node": "append", "from_port": "array", "to_node": "get", "to_port": "array"},
                {"from_node": "append", "from_port": "array", "to_node": "length", "to_port": "value"},
                {"from_node": "end", "from_port": "value", "to_node": "get", "to_port": "index"},
            ],
            "output_nodes": [
                {"node_id": "get", "port": "value", "alias": "value"},
                {"node_id": "length", "port": "length", "alias": "length"},
            ],
        },
        {"value": 4, "length": 4},
    )


def test_map_get_with_input_values() -> None:
    run_graph(
        "map_get_with_input_values",
        {
            "nodes": [
                {
                    "id": "get",
                    "type": "core.container.get",
                    "params": {},
                    "input_values": {"map": {"a": 5}, "key": "a", "default": 0},
                }
            ],
            "links": [],
            "output_nodes": [{"node_id": "get", "port": "value", "alias": "value"}],
        },
        {"value": 5},
    )


def test_control_multiple_parents() -> None:
    result = run_graph(
        "control_multiple_parents",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "value", "type": "core.literal.int", "params": {"value": 9}},
                {"id": "set_a", "type": "core.var.set", "params": {"name": "a"}},
                {"id": "set_b", "type": "core.var.set", "params": {"name": "b"}},
                {"id": "get_a", "type": "core.var.get", "params": {"name": "a", "default": 0}},
            ],
            "links": [
                {"from_node": "value", "from_port": "value", "to_node": "set_a", "to_port": "value"},
                {"from_node": "value", "from_port": "value", "to_node": "set_b", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "set_a", "to_port": "control_in", "kind": "control"},
                {"from_node": "start", "from_port": "control_out", "to_node": "set_b", "to_port": "control_in", "kind": "control"},
                {"from_node": "set_a", "from_port": "control_out", "to_node": "get_a", "to_port": "control_in", "kind": "control"},
                {"from_node": "set_b", "from_port": "control_out", "to_node": "get_a", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_a", "port": "value", "alias": "value"}],
        },
        {"value": 9},
    )
    assert_trace_order(result, "set_a", "get_a")
    assert_trace_order(result, "set_b", "get_a")


def test_missing_node_type() -> None:
    assert_raises(
        "missing_node_type",
        {
            "nodes": [
                {"id": "a", "params": {"value": 1}},
            ],
            "links": [],
        },
        expected_code="missing_type",
    )


def test_unknown_node_type() -> None:
    assert_raises(
        "unknown_node_type",
        {
            "nodes": [
                {"id": "a", "type": "core.unknown.node", "params": {}},
            ],
            "links": [],
        },
        expected_code="unknown_node",
    )


def test_duplicate_node_id() -> None:
    assert_raises(
        "duplicate_node_id",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            ],
            "links": [],
        },
        expected_code="duplicate_id",
    )


def test_missing_output_port() -> None:
    assert_raises(
        "missing_output_port",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "bad_port", "to_node": "b", "to_port": "a"},
            ],
        },
        expected_code="missing_output_port",
    )


def test_missing_input_port() -> None:
    assert_raises(
        "missing_input_port",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "b", "to_port": "bad_port"},
            ],
        },
        expected_code="missing_input_port",
    )


def test_duplicate_link() -> None:
    assert_raises(
        "duplicate_link",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "b", "to_port": "a"},
                {"from_node": "a", "from_port": "value", "to_node": "b", "to_port": "a"},
            ],
        },
        expected_code="duplicate_link",
    )


def test_type_mismatch() -> None:
    assert_raises(
        "type_mismatch",
        {
            "nodes": [
                {"id": "text", "type": "core.literal.string", "params": {"value": "abc"}},
                {"id": "and", "type": "core.logic.and", "params": {}},
            ],
            "links": [
                {"from_node": "text", "from_port": "value", "to_node": "and", "to_port": "a"},
            ],
        },
        expected_code="type_mismatch",
    )


def test_output_port_validation() -> None:
    assert_raises(
        "output_port_validation",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
            ],
            "links": [],
            "output_nodes": [{"node_id": "a", "port": "missing", "alias": "x"}],
        },
        expected_code="missing_output_port",
    )


async def _run_parallel() -> int:
    parallel_graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "split", "type": "core.util.splitter", "params": {}},
            {"id": "d1", "type": "core.util.delay", "params": {"delay_ms": 150}},
            {"id": "d2", "type": "core.util.delay", "params": {"delay_ms": 150}},
            {"id": "d3", "type": "core.util.delay", "params": {"delay_ms": 150}},
            {"id": "merge", "type": "core.util.merger", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "split", "to_port": "input"},
            {"from_node": "split", "from_port": "out_a", "to_node": "d1", "to_port": "value"},
            {"from_node": "split", "from_port": "out_b", "to_node": "d2", "to_port": "value"},
            {"from_node": "split", "from_port": "out_c", "to_node": "d3", "to_port": "value"},
            {"from_node": "d1", "from_port": "value", "to_node": "merge", "to_port": "in_a"},
            {"from_node": "d2", "from_port": "value", "to_node": "merge", "to_port": "in_b"},
            {"from_node": "d3", "from_port": "value", "to_node": "merge", "to_port": "in_c"},
        ],
        "output_nodes": [{"node_id": "merge", "port": "sum", "alias": "sum"}],
    }

    executor = GraphExecutor(parallel_graph)
    running = 0
    max_running = 0
    async for event in executor.run_streaming():
        if event.event_type == "node_started":
            running += 1
            max_running = max(max_running, running)
        elif event.event_type in {"node_completed", "node_error", "node_skipped", "node_cached"}:
            running = max(0, running - 1)
    return max_running


def test_parallel_branches() -> None:
    max_running = asyncio.run(_run_parallel())
    if max_running < 2:
        raise AssertionError(f"parallel_branches expected concurrency, got {max_running}")
    print(f"parallel_branches: PASS max_running={max_running}")


def test_breakpoints_stop_execution() -> None:
    result = run_graph(
        "breakpoints_stop_execution",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "add", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        },
        expected_outputs={},
        options={"breakpoints": ["add"]},
    )
    trace_ids = [entry.get("node_id") for entry in result.get("trace", [])]
    if "add" in trace_ids:
        raise AssertionError("breakpoints_stop_execution expected add to be skipped")


def test_max_steps_limits_execution() -> None:
    result = run_graph(
        "max_steps_limits_execution",
        {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "add", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        },
        expected_outputs={},
        options={"max_steps": 1},
    )
    if len(result.get("trace", [])) != 1:
        raise AssertionError("max_steps_limits_execution expected exactly 1 executed node")


def test_cache_reuse_and_clear() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }

    GraphExecutor.clear_cache()
    first = run_graph("cache_first_run", graph, {"sum": 5.0})
    if has_cached_logs(first):
        raise AssertionError("cache_first_run should not be cached")

    second = run_graph("cache_second_run", graph, {"sum": 5.0})
    if not has_cached_logs(second):
        raise AssertionError("cache_second_run expected cached logs")

    GraphExecutor.clear_cache()
    third = run_graph("cache_after_clear", graph, {"sum": 5.0})
    if has_cached_logs(third):
        raise AssertionError("cache_after_clear should not be cached")


def test_cache_clear_by_type() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }

    GraphExecutor.clear_cache()
    run_graph("cache_by_type_first", graph, {"sum": 5.0})
    cached = run_graph("cache_by_type_second", graph, {"sum": 5.0})
    if not has_cached_logs_for_node(cached, "add"):
        raise AssertionError("cache_by_type_second expected add to be cached")

    GraphExecutor.clear_cache_by_type("core.math.add")
    third = run_graph("cache_by_type_after_clear", graph, {"sum": 5.0})
    if has_cached_logs_for_node(third, "add"):
        raise AssertionError("cache_by_type_after_clear add should not be cached")


async def _run_streaming_events() -> list[str]:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    executor = GraphExecutor(graph)
    events: list[str] = []
    async for event in executor.run_streaming():
        events.append(event.event_type)
    return events


def test_streaming_event_order() -> None:
    events = asyncio.run(_run_streaming_events())
    if not events or events[0] != "start":
        raise AssertionError("streaming_event_order expected start event first")
    if events[-1] != "complete":
        raise AssertionError("streaming_event_order expected complete event last")


async def _run_streaming_progress() -> list[dict]:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    executor = GraphExecutor(graph)
    events: list[dict] = []
    async for event in executor.run_streaming():
        events.append({"type": event.event_type, "progress": event.progress})
    return events


def test_streaming_progress_complete() -> None:
    events = asyncio.run(_run_streaming_progress())
    assert_progress_complete(events)
    assert_progress_monotonic(events)


async def _run_streaming_with_cancel() -> dict:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "d1", "type": "core.util.delay", "params": {"delay_ms": 300}},
            {"id": "d2", "type": "core.util.delay", "params": {"delay_ms": 300}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "d1", "to_port": "value"},
            {"from_node": "d1", "from_port": "value", "to_node": "d2", "to_port": "value"},
        ],
        "output_nodes": [{"node_id": "d2", "port": "value", "alias": "value"}],
    }
    executor = GraphExecutor(graph)
    events: list[dict] = []
    cancelled = False
    async for event in executor.run_streaming():
        events.append(
            {
                "type": event.event_type,
                "total": event.total_nodes,
                "completed": event.completed_nodes,
                "progress": event.progress,
            }
        )
        if event.event_type == "node_started" and not cancelled:
            GraphExecutor.cancel_execution(event.execution_id or "")
            cancelled = True
    return {"events": events, "cancelled": cancelled}


def test_streaming_cancel_execution() -> None:
    result = asyncio.run(_run_streaming_with_cancel())
    events = result["events"]
    if not result["cancelled"]:
        raise AssertionError("streaming_cancel_execution did not trigger cancel")
    complete_event = next((e for e in events if e["type"] == "complete"), None)
    if not complete_event:
        raise AssertionError("streaming_cancel_execution expected complete event")
    completed = complete_event.get("completed") or 0
    total = complete_event.get("total") or 0
    if completed >= total and not any(e["type"] == "node_skipped" for e in events):
        raise AssertionError("streaming_cancel_execution expected early termination or skipped nodes")


async def _run_streaming_cancel_node() -> dict:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "split", "type": "core.util.splitter", "params": {}},
            {"id": "d1", "type": "core.util.delay", "params": {"delay_ms": 200}},
            {"id": "d2", "type": "core.util.delay", "params": {"delay_ms": 200}},
            {"id": "merge", "type": "core.util.merger", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "split", "to_port": "input"},
            {"from_node": "split", "from_port": "out_a", "to_node": "d1", "to_port": "value"},
            {"from_node": "split", "from_port": "out_b", "to_node": "d2", "to_port": "value"},
            {"from_node": "d1", "from_port": "value", "to_node": "merge", "to_port": "in_a"},
            {"from_node": "d2", "from_port": "value", "to_node": "merge", "to_port": "in_b"},
        ],
        "output_nodes": [{"node_id": "merge", "port": "sum", "alias": "sum"}],
    }
    executor = GraphExecutor(graph)
    events: list[dict] = []
    cancelled = False
    async for event in executor.run_streaming():
        events.append({"type": event.event_type, "node_id": event.node_id})
        if event.event_type == "node_started" and event.node_id == "d1" and not cancelled:
            GraphExecutor.cancel_node(event.execution_id or "", "d2")
            cancelled = True
    return {"events": events, "cancelled": cancelled}


def test_streaming_cancel_node() -> None:
    result = asyncio.run(_run_streaming_cancel_node())
    events = result["events"]
    if not result["cancelled"]:
        raise AssertionError("streaming_cancel_node did not trigger cancel")
    skipped = [e for e in events if e["type"] == "node_skipped" and e.get("node_id") == "d2"]
    if not skipped:
        raise AssertionError("streaming_cancel_node expected d2 to be skipped")


def test_selection_mode_executes_dependencies_only() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "add", "type": "core.math.add", "params": {}},
            {"id": "x", "type": "core.literal.int", "params": {"value": 5}},
            {"id": "mul", "type": "core.math.multiply", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            {"from_node": "x", "from_port": "value", "to_node": "mul", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "mul", "to_port": "b"},
        ],
        "output_nodes": [
            {"node_id": "add", "port": "sum", "alias": "sum"},
            {"node_id": "mul", "port": "product", "alias": "product"},
        ],
    }

    result = run_graph(
        "selection_mode_dependencies_only",
        graph,
        expected_outputs={"sum": 5.0},
        options={"mode": "selection", "target_nodes": ["add"]},
    )
    trace_ids = [entry.get("node_id") for entry in result.get("trace", [])]
    if "mul" in trace_ids:
        raise AssertionError("selection_mode_dependencies_only expected mul to be skipped")
    if "add" not in trace_ids:
        raise AssertionError("selection_mode_dependencies_only expected add to run")


async def _run_streaming_max_steps() -> dict:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "c", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    executor = GraphExecutor(graph, options={"max_steps": 1})
    events: list[dict] = []
    async for event in executor.run_streaming():
        events.append(
            {
                "type": event.event_type,
                "total": event.total_nodes,
                "completed": event.completed_nodes,
            }
        )
    return {"events": events}


def test_streaming_max_steps_limits_execution() -> None:
    result = asyncio.run(_run_streaming_max_steps())
    complete = next((e for e in result["events"] if e["type"] == "complete"), None)
    if not complete:
        raise AssertionError("streaming_max_steps_limits_execution expected complete event")
    completed = complete.get("completed") or 0
    if completed > 1:
        raise AssertionError(f"streaming_max_steps_limits_execution expected <=1 completed, got {completed}")


async def _run_fail_fast_streaming(fail_fast: bool) -> list[dict]:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.string", "params": {"value": "abc"}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 1}},
            {"id": "cmp", "type": "core.logic.compare", "params": {"op": ">"}},
            {"id": "value", "type": "core.literal.int", "params": {"value": 5}},
            {"id": "delay", "type": "core.util.delay", "params": {"delay_ms": 300}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "cmp", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "cmp", "to_port": "b"},
            {"from_node": "value", "from_port": "value", "to_node": "delay", "to_port": "value"},
        ],
        "output_nodes": [{"node_id": "delay", "port": "value", "alias": "value"}],
    }
    executor = GraphExecutor(graph, options={"fail_fast": fail_fast, "max_workers": 2})
    events: list[dict] = []
    async for event in executor.run_streaming():
        if event.node_id:
            events.append({"type": event.event_type, "node_id": event.node_id})
    return events


def test_fail_fast_cancels_parallel_tasks() -> None:
    events = asyncio.run(_run_fail_fast_streaming(True))
    error_index = next((i for i, e in enumerate(events) if e["type"] == "node_error" and e.get("node_id") == "cmp"), None)
    if error_index is None:
        raise AssertionError("fail_fast_cancels_parallel_tasks expected cmp error")
    for entry in events[error_index + 1:]:
        if entry["type"] in {"node_queued", "node_started"}:
            raise AssertionError("fail_fast_cancels_parallel_tasks expected no new nodes queued after error")


def test_fail_fast_false_allows_parallel_completion() -> None:
    events = asyncio.run(_run_fail_fast_streaming(False))
    delay_events = [e["type"] for e in events if e.get("node_id") == "delay"]
    if "node_completed" not in delay_events:
        raise AssertionError("fail_fast_false_allows_parallel_completion expected delay to complete")


async def _run_streaming_counts() -> dict:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    executor = GraphExecutor(graph)
    events: list[dict] = []
    async for event in executor.run_streaming():
        if event.event_type == "complete":
            events.append(
                {
                    "type": event.event_type,
                    "total": event.total_nodes,
                    "completed": event.completed_nodes,
                }
            )
    return {"events": events}


def test_streaming_counts_match_total() -> None:
    result = asyncio.run(_run_streaming_counts())
    complete = next((e for e in result["events"] if e["type"] == "complete"), None)
    if not complete:
        raise AssertionError("streaming_counts_match_total expected complete event")
    total = complete.get("total") or 0
    completed = complete.get("completed") or 0
    if total != completed:
        raise AssertionError(f"streaming_counts_match_total expected {total} completed, got {completed}")


def test_streaming_node_event_order() -> None:
    async def run() -> list[dict]:
        graph = {
            "nodes": [
                {"id": "a", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "add", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        }
        executor = GraphExecutor(graph)
        events: list[dict] = []
        async for event in executor.run_streaming():
            if event.node_id:
                events.append({"type": event.event_type, "node_id": event.node_id})
        return events

    events = asyncio.run(run())
    assert_node_event_order(events, "a")
    assert_node_event_order(events, "b")
    assert_node_event_order(events, "add")


def test_loop_body_uses_data_dependencies() -> None:
    run_graph(
        "loop_body_data_dependencies",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "first", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "last", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "loop", "type": "core.control.for", "params": {}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "sum", "type": "core.util.merger", "params": {}},
            ],
            "links": [
                {"from_node": "first", "from_port": "value", "to_node": "loop", "to_port": "first_index"},
                {"from_node": "last", "from_port": "value", "to_node": "loop", "to_port": "last_index"},
                {"from_node": "loop", "from_port": "index", "to_node": "add", "to_port": "a"},
                {"from_node": "loop", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "add", "from_port": "sum", "to_node": "sum", "to_port": "in_a"},
                {"from_node": "add", "from_port": "sum", "to_node": "sum", "to_port": "in_b"},
                {"from_node": "add", "from_port": "sum", "to_node": "sum", "to_port": "in_c"},
                {"from_node": "start", "from_port": "control_out", "to_node": "loop", "to_port": "control_in", "kind": "control"},
                {"from_node": "loop", "from_port": "loop_body", "to_node": "add", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
        },
        {"sum": 6.0},
    )


def test_randomized_dag_stress() -> None:
    rng = random.Random(7)
    node_count = 18
    nodes = [{"id": f"n{i}", "type": "core.literal.int", "params": {"value": i}} for i in range(6)]
    nodes.append({"id": "sum0", "type": "core.math.add", "params": {}})
    links = [
        {"from_node": "n0", "from_port": "value", "to_node": "sum0", "to_port": "a"},
        {"from_node": "n1", "from_port": "value", "to_node": "sum0", "to_port": "b"},
    ]
    for i in range(2, node_count):
        nodes.append({"id": f"sum{i}", "type": "core.math.add", "params": {}})
        src_a = rng.choice(nodes[: len(nodes) - 1])["id"]
        src_b = rng.choice(nodes[: len(nodes) - 1])["id"]
        links.append({"from_node": src_a, "from_port": "sum" if src_a.startswith("sum") else "value", "to_node": f"sum{i}", "to_port": "a"})
        links.append({"from_node": src_b, "from_port": "sum" if src_b.startswith("sum") else "value", "to_node": f"sum{i}", "to_port": "b"})

    graph = {
        "nodes": nodes,
        "links": links,
        "output_nodes": [{"node_id": f"sum{node_count-1}", "port": "sum", "alias": "sum"}],
    }
    result = GraphExecutor(graph).run()
    if "sum" not in result.get("outputs", {}):
        raise AssertionError("randomized_dag_stress expected sum output")


def test_cycle_detection_data() -> None:
    assert_raises(
        "cycle_detection_data",
        {
            "nodes": [
                {"id": "a", "type": "core.math.add", "params": {}},
                {"id": "b", "type": "core.math.add", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "sum", "to_node": "b", "to_port": "a"},
                {"from_node": "b", "from_port": "sum", "to_node": "a", "to_port": "a"},
            ],
        },
    )


def test_cycle_detection_control() -> None:
    assert_raises(
        "cycle_detection_control",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "a", "type": "core.util.delay", "params": {"delay_ms": 10}},
                {"id": "b", "type": "core.util.delay", "params": {"delay_ms": 10}},
            ],
            "links": [
                {"from_node": "start", "from_port": "control_out", "to_node": "a", "to_port": "control_in", "kind": "control"},
                {"from_node": "a", "from_port": "control_out", "to_node": "b", "to_port": "control_in", "kind": "control"},
                {"from_node": "b", "from_port": "control_out", "to_node": "a", "to_port": "control_in", "kind": "control"},
            ],
        },
    )


def test_default_outputs_collection() -> None:
    result = run_graph(
        "default_outputs_collection",
        {
            "nodes": [
                {"id": "lit", "type": "core.literal.int", "params": {"value": 7}},
            ],
            "links": [],
        },
        expected_outputs={},
    )
    if "lit.value" not in result.get("outputs", {}):
        raise AssertionError("default_outputs_collection expected lit.value output")


def test_variable_nodes_not_cached() -> None:
    graph = {
        "nodes": [
            {"id": "start", "type": "core.control.start", "params": {}},
            {"id": "value", "type": "core.literal.int", "params": {"value": 9}},
            {"id": "set", "type": "core.var.set", "params": {"name": "x"}},
            {"id": "get", "type": "core.var.get", "params": {"name": "x", "default": 0}},
        ],
        "links": [
            {"from_node": "value", "from_port": "value", "to_node": "set", "to_port": "value"},
            {"from_node": "start", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
            {"from_node": "set", "from_port": "control_out", "to_node": "get", "to_port": "control_in", "kind": "control"},
        ],
        "output_nodes": [{"node_id": "get", "port": "value", "alias": "value"}],
    }
    GraphExecutor.clear_cache()
    run_graph("variable_nodes_not_cached_first", graph, {"value": 9})
    second = run_graph("variable_nodes_not_cached_second", graph, {"value": 9})
    if has_cached_logs_for_node(second, "set") or has_cached_logs_for_node(second, "get"):
        raise AssertionError("variable_nodes_not_cached expected no cache logs for var nodes")


def test_cache_invalidation_on_param_change() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "add", "type": "core.math.add", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    GraphExecutor.clear_cache()
    run_graph("cache_param_change_first", graph, {"sum": 5.0})
    cached = run_graph("cache_param_change_second", graph, {"sum": 5.0})
    if not has_cached_logs_for_node(cached, "add"):
        raise AssertionError("cache_param_change_second expected add to be cached")

    graph["nodes"][1]["params"]["value"] = 4
    third = run_graph("cache_param_change_third", graph, {"sum": 6.0})
    if has_cached_logs_for_node(third, "add"):
        raise AssertionError("cache_param_change_third expected add to recompute")


def test_cache_invalidation_on_input_values_change() -> None:
    graph = {
        "nodes": [
            {"id": "add", "type": "core.math.add", "params": {}, "input_values": {"a": 1, "b": 2}},
        ],
        "links": [],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    GraphExecutor.clear_cache()
    run_graph("cache_input_values_first", graph, {"sum": 3.0})
    cached = run_graph("cache_input_values_second", graph, {"sum": 3.0})
    if not has_cached_logs_for_node(cached, "add"):
        raise AssertionError("cache_input_values_second expected add to be cached")

    graph["nodes"][0]["input_values"]["b"] = 5
    third = run_graph("cache_input_values_third", graph, {"sum": 6.0})
    if has_cached_logs_for_node(third, "add"):
        raise AssertionError("cache_input_values_third expected add to recompute")


def test_large_randomized_dag_mixed_types() -> None:
    rng = random.Random(11)
    literals: list[dict] = []
    for i in range(10):
        literals.append({"id": f"lit{i}", "type": "core.literal.int", "params": {"value": i}})
    nodes = literals[:]
    links: list[dict] = []

    for i in range(10, 30):
        node_id = f"add{i}"
        nodes.append({"id": node_id, "type": "core.math.add", "params": {}})
        src_a = rng.choice(nodes[:-1])
        src_b = rng.choice(nodes[:-1])
        links.append({"from_node": src_a["id"], "from_port": "sum" if src_a["id"].startswith("add") else "value", "to_node": node_id, "to_port": "a"})
        links.append({"from_node": src_b["id"], "from_port": "sum" if src_b["id"].startswith("add") else "value", "to_node": node_id, "to_port": "b"})

    graph = {
        "nodes": nodes,
        "links": links,
        "output_nodes": [{"node_id": "add29", "port": "sum", "alias": "sum"}],
    }
    result = GraphExecutor(graph).run()
    if "sum" not in result.get("outputs", {}):
        raise AssertionError("large_randomized_dag_mixed_types expected sum output")


def test_nested_loop_with_data_dependency() -> None:
    run_graph(
        "nested_loop_with_data_dependency",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "outer_first", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "outer_last", "type": "core.literal.int", "params": {"value": 1}},
                {"id": "inner_count", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "outer", "type": "core.control.for", "params": {}},
                {"id": "inner", "type": "core.control.repeat", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "outer_first", "from_port": "value", "to_node": "outer", "to_port": "first_index"},
                {"from_node": "outer_last", "from_port": "value", "to_node": "outer", "to_port": "last_index"},
                {"from_node": "inner_count", "from_port": "value", "to_node": "inner", "to_port": "count"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "inner", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "outer", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "loop_body", "to_node": "inner", "to_port": "control_in", "kind": "control"},
                {"from_node": "inner", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": 2.0},
    )


def test_parallel_branches_with_control_chain() -> None:
    run_graph(
        "parallel_branches_with_control_chain",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "value", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "split", "type": "core.util.splitter", "params": {}},
                {"id": "d1", "type": "core.util.delay", "params": {"delay_ms": 100}},
                {"id": "d2", "type": "core.util.delay", "params": {"delay_ms": 100}},
                {"id": "d3", "type": "core.util.delay", "params": {"delay_ms": 100}},
                {"id": "merge", "type": "core.util.merger", "params": {}},
            ],
            "links": [
                {"from_node": "value", "from_port": "value", "to_node": "split", "to_port": "input"},
                {"from_node": "split", "from_port": "out_a", "to_node": "d1", "to_port": "value"},
                {"from_node": "split", "from_port": "out_b", "to_node": "d2", "to_port": "value"},
                {"from_node": "split", "from_port": "out_c", "to_node": "d3", "to_port": "value"},
                {"from_node": "d1", "from_port": "value", "to_node": "merge", "to_port": "in_a"},
                {"from_node": "d2", "from_port": "value", "to_node": "merge", "to_port": "in_b"},
                {"from_node": "d3", "from_port": "value", "to_node": "merge", "to_port": "in_c"},
                {"from_node": "start", "from_port": "control_out", "to_node": "split", "to_port": "control_in", "kind": "control"},
                {"from_node": "split", "from_port": "control_out", "to_node": "d1", "to_port": "control_in", "kind": "control"},
                {"from_node": "split", "from_port": "control_out", "to_node": "d2", "to_port": "control_in", "kind": "control"},
                {"from_node": "split", "from_port": "control_out", "to_node": "d3", "to_port": "control_in", "kind": "control"},
                {"from_node": "d1", "from_port": "control_out", "to_node": "merge", "to_port": "control_in", "kind": "control"},
                {"from_node": "d2", "from_port": "control_out", "to_node": "merge", "to_port": "control_in", "kind": "control"},
                {"from_node": "d3", "from_port": "control_out", "to_node": "merge", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "merge", "port": "sum", "alias": "sum"}],
        },
        {"sum": 6.0},
    )


def test_large_mixed_control_data_graph() -> None:
    run_graph(
        "large_mixed_control_data_graph",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
                {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
                {"id": "c", "type": "core.literal.int", "params": {"value": 4}},
                {"id": "add1", "type": "core.math.add", "params": {}},
                {"id": "add2", "type": "core.math.add", "params": {}},
                {"id": "mul", "type": "core.math.multiply", "params": {}},
                {"id": "delay1", "type": "core.util.delay", "params": {"delay_ms": 50}},
                {"id": "delay2", "type": "core.util.delay", "params": {"delay_ms": 50}},
                {"id": "merge", "type": "core.util.merger", "params": {}},
            ],
            "links": [
                {"from_node": "a", "from_port": "value", "to_node": "add1", "to_port": "a"},
                {"from_node": "b", "from_port": "value", "to_node": "add1", "to_port": "b"},
                {"from_node": "add1", "from_port": "sum", "to_node": "add2", "to_port": "a"},
                {"from_node": "c", "from_port": "value", "to_node": "add2", "to_port": "b"},
                {"from_node": "add2", "from_port": "sum", "to_node": "mul", "to_port": "a"},
                {"from_node": "a", "from_port": "value", "to_node": "mul", "to_port": "b"},
                {"from_node": "mul", "from_port": "product", "to_node": "delay1", "to_port": "value"},
                {"from_node": "add2", "from_port": "sum", "to_node": "delay2", "to_port": "value"},
                {"from_node": "delay1", "from_port": "value", "to_node": "merge", "to_port": "in_a"},
                {"from_node": "delay2", "from_port": "value", "to_node": "merge", "to_port": "in_b"},
                {"from_node": "add1", "from_port": "sum", "to_node": "merge", "to_port": "in_c"},
                {"from_node": "start", "from_port": "control_out", "to_node": "add1", "to_port": "control_in", "kind": "control"},
                {"from_node": "add1", "from_port": "control_out", "to_node": "add2", "to_port": "control_in", "kind": "control"},
                {"from_node": "add2", "from_port": "control_out", "to_node": "mul", "to_port": "control_in", "kind": "control"},
                {"from_node": "mul", "from_port": "control_out", "to_node": "delay1", "to_port": "control_in", "kind": "control"},
                {"from_node": "mul", "from_port": "control_out", "to_node": "delay2", "to_port": "control_in", "kind": "control"},
                {"from_node": "delay1", "from_port": "control_out", "to_node": "merge", "to_port": "control_in", "kind": "control"},
                {"from_node": "delay2", "from_port": "control_out", "to_node": "merge", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "merge", "port": "sum", "alias": "sum"}],
        },
        {"sum": 32.0},
    )


def test_randomized_loop_body_dependencies() -> None:
    rng = random.Random(21)
    outer_first = 0
    outer_last = 2
    inner_count = 3
    expected = 0
    for _ in range(outer_first, outer_last + 1):
        for idx in range(inner_count):
            expected += idx

    run_graph(
        "randomized_loop_body_dependencies",
        {
            "nodes": [
                {"id": "start", "type": "core.control.start", "params": {}},
                {"id": "zero", "type": "core.literal.int", "params": {"value": 0}},
                {"id": "outer_first", "type": "core.literal.int", "params": {"value": outer_first}},
                {"id": "outer_last", "type": "core.literal.int", "params": {"value": outer_last}},
                {"id": "inner_count", "type": "core.literal.int", "params": {"value": inner_count}},
                {"id": "decl", "type": "core.var.declare", "params": {"name": "acc"}},
                {"id": "outer", "type": "core.control.for", "params": {}},
                {"id": "inner", "type": "core.control.repeat", "params": {}},
                {"id": "get", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
                {"id": "add", "type": "core.math.add", "params": {}},
                {"id": "set", "type": "core.var.set", "params": {"name": "acc"}},
                {"id": "get_end", "type": "core.var.get", "params": {"name": "acc", "default": 0}},
            ],
            "links": [
                {"from_node": "zero", "from_port": "value", "to_node": "decl", "to_port": "value"},
                {"from_node": "outer_first", "from_port": "value", "to_node": "outer", "to_port": "first_index"},
                {"from_node": "outer_last", "from_port": "value", "to_node": "outer", "to_port": "last_index"},
                {"from_node": "inner_count", "from_port": "value", "to_node": "inner", "to_port": "count"},
                {"from_node": "get", "from_port": "value", "to_node": "add", "to_port": "a"},
                {"from_node": "inner", "from_port": "index", "to_node": "add", "to_port": "b"},
                {"from_node": "add", "from_port": "sum", "to_node": "set", "to_port": "value"},
                {"from_node": "start", "from_port": "control_out", "to_node": "decl", "to_port": "control_in", "kind": "control"},
                {"from_node": "decl", "from_port": "control_out", "to_node": "outer", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "loop_body", "to_node": "inner", "to_port": "control_in", "kind": "control"},
                {"from_node": "inner", "from_port": "loop_body", "to_node": "get", "to_port": "control_in", "kind": "control"},
                {"from_node": "get", "from_port": "control_out", "to_node": "add", "to_port": "control_in", "kind": "control"},
                {"from_node": "add", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
                {"from_node": "outer", "from_port": "completed", "to_node": "get_end", "to_port": "control_in", "kind": "control"},
            ],
            "output_nodes": [{"node_id": "get_end", "port": "value", "alias": "sum"}],
        },
        {"sum": float(expected)},
    )


def test_cache_clear_by_type_multi_node() -> None:
    graph = {
        "nodes": [
            {"id": "a", "type": "core.literal.int", "params": {"value": 2}},
            {"id": "b", "type": "core.literal.int", "params": {"value": 3}},
            {"id": "c", "type": "core.literal.int", "params": {"value": 4}},
            {"id": "add1", "type": "core.math.add", "params": {}},
            {"id": "add2", "type": "core.math.add", "params": {}},
            {"id": "mul", "type": "core.math.multiply", "params": {}},
        ],
        "links": [
            {"from_node": "a", "from_port": "value", "to_node": "add1", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "add1", "to_port": "b"},
            {"from_node": "add1", "from_port": "sum", "to_node": "add2", "to_port": "a"},
            {"from_node": "c", "from_port": "value", "to_node": "add2", "to_port": "b"},
            {"from_node": "add2", "from_port": "sum", "to_node": "mul", "to_port": "a"},
            {"from_node": "b", "from_port": "value", "to_node": "mul", "to_port": "b"},
        ],
        "output_nodes": [{"node_id": "mul", "port": "product", "alias": "product"}],
    }
    GraphExecutor.clear_cache()
    run_graph("cache_clear_multi_first", graph, {"product": 27.0})
    cached = run_graph("cache_clear_multi_second", graph, {"product": 27.0})
    if not has_cached_logs(cached):
        raise AssertionError("cache_clear_multi_second expected cached logs")

    GraphExecutor.clear_cache_by_type("core.math.add")
    third = run_graph("cache_clear_multi_after", graph, {"product": 27.0})
    if has_cached_logs_for_node(third, "add1") or has_cached_logs_for_node(third, "add2"):
        raise AssertionError("cache_clear_multi_after expected add nodes to recompute")


def main() -> None:
    test_simple_add()
    test_string_add()
    test_make_array()
    test_for_loop_sum()
    test_while_loop_sum()
    test_control_ordering()
    test_loop_completed_uses_last_index()
    test_repeat_loop_sum()
    test_reverse_for_loop_sum()
    test_while_loop_no_iterations()
    test_nested_loops_increment()
    test_logic_compare_and_boolean_ops()
    test_string_concat()
    test_casting_nodes()
    test_math_ops()
    test_container_nodes()
    test_map_get_with_input_values()
    test_control_multiple_parents()
    test_missing_node_type()
    test_unknown_node_type()
    test_duplicate_node_id()
    test_missing_output_port()
    test_missing_input_port()
    test_duplicate_link()
    test_type_mismatch()
    test_output_port_validation()
    test_breakpoints_stop_execution()
    test_max_steps_limits_execution()
    test_cache_reuse_and_clear()
    test_cache_clear_by_type()
    test_streaming_event_order()
    test_streaming_progress_complete()
    test_streaming_cancel_execution()
    test_streaming_cancel_node()
    test_selection_mode_executes_dependencies_only()
    test_streaming_max_steps_limits_execution()
    test_fail_fast_cancels_parallel_tasks()
    test_fail_fast_false_allows_parallel_completion()
    test_streaming_counts_match_total()
    test_streaming_node_event_order()
    test_loop_body_uses_data_dependencies()
    test_randomized_dag_stress()
    test_cycle_detection_data()
    test_cycle_detection_control()
    test_default_outputs_collection()
    test_variable_nodes_not_cached()
    test_cache_invalidation_on_param_change()
    test_cache_invalidation_on_input_values_change()
    test_large_randomized_dag_mixed_types()
    test_nested_loop_with_data_dependency()
    test_parallel_branches_with_control_chain()
    test_large_mixed_control_data_graph()
    test_randomized_loop_body_dependencies()
    test_cache_clear_by_type_multi_node()
    test_parallel_branches()
    print("All checks passed.")


if __name__ == "__main__":
    main()
