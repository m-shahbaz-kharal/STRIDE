from __future__ import annotations

import asyncio

from .runner import GraphExecutor


def assert_eq(label: str, got: object, expected: object) -> None:
    if got != expected:
        raise AssertionError(f"{label} expected {expected!r}, got {got!r}")


def run_graph(name: str, graph: dict, expected_outputs: dict | None = None) -> dict:
    result = GraphExecutor(graph).run()
    outputs = result["outputs"]
    if expected_outputs:
        for key, expected in expected_outputs.items():
            assert_eq(f"{name}:{key}", outputs.get(key), expected)
    print(f"{name}: PASS outputs={outputs}")
    return result


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


def main() -> None:
    test_simple_add()
    test_string_add()
    test_make_array()
    test_for_loop_sum()
    test_while_loop_sum()
    test_parallel_branches()
    print("All checks passed.")


if __name__ == "__main__":
    main()
