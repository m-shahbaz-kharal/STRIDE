from __future__ import annotations

from .runner import GraphExecutor


SAMPLE_GRAPH = {
    "nodes": [
        {
            "id": "const_a",
            "type": "constant.number",
            "params": {"value": 12},
        },
        {
            "id": "const_b",
            "type": "constant.number",
            "params": {"value": 7},
        },
        {
            "id": "adder",
            "type": "math.add",
            "params": {},
        },
    ],
    "links": [
        {"from_node": "const_a", "from_port": "value", "to_node": "adder", "to_port": "a"},
        {"from_node": "const_b", "from_port": "value", "to_node": "adder", "to_port": "b"},
    ],
    "output_nodes": [
        {"node_id": "adder", "port": "sum", "alias": "a_plus_b"}
    ],
}


def run_sample() -> None:
    executor = GraphExecutor(SAMPLE_GRAPH)
    result = executor.run()
    print("Sample graph result:", result["outputs"])
    for step in result["trace"]:
        print(f" - {step['node_id']}: {step['outputs']}")


if __name__ == "__main__":
    run_sample()
