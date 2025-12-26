from __future__ import annotations

from app.runner import GraphExecutor


def run_graph(graph):
    executor = GraphExecutor(graph)
    result = executor.run()
    return result


def test_control_edges_and_variables():
    graph = {
        "nodes": [
            {"id": "declare", "type": "core.var.declare", "params": {"name": "x"}},
            {"id": "set", "type": "core.var.set", "params": {"name": "x"}},
            {"id": "const", "type": "core.literal.int", "params": {"value": 5}},
            {"id": "get", "type": "core.var.get", "params": {"name": "x", "default": 0}},
        ],
        "links": [
            {"from_node": "declare", "from_port": "control_out", "to_node": "set", "to_port": "control_in", "kind": "control"},
            {"from_node": "declare", "from_port": "control_out", "to_node": "get", "to_port": "control_in", "kind": "control"},
            {"from_node": "const", "from_port": "value", "to_node": "set", "to_port": "value"},
            {"from_node": "set", "from_port": "value", "to_node": "get", "to_port": "default"},
        ],
        "output_nodes": [{"node_id": "get", "port": "value", "alias": "result"}],
    }
    result = run_graph(graph)
    assert result["outputs"]["result"] == 5


def test_inline_input_values():
    graph = {
        "nodes": [
            {
                "id": "add",
                "type": "core.math.add",
                "input_values": {"a": 2, "b": 3},
            },
        ],
        "links": [],
        "output_nodes": [{"node_id": "add", "port": "sum", "alias": "sum"}],
    }
    result = run_graph(graph)
    assert result["outputs"]["sum"] == 5
