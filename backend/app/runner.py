from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .nodes import ExecutionContext, NodeBase, get_node


class GraphExecutionError(Exception):
    pass


@dataclass
class Link:
    from_node: str
    from_port: str
    to_node: str
    to_port: str


@dataclass
class ExecutionUnit:
    device: str
    nodes: List[Dict[str, Any]] = field(default_factory=list)


class GraphExecutor:
    """Minimal graph compiler/executor that respects simple device hints."""

    def __init__(self, graph_definition: Dict[str, Any]) -> None:
        self.definition = graph_definition
        self.nodes: Dict[str, NodeBase] = {}
        self.links: List[Link] = []
        self.input_map: Dict[str, Dict[str, Link]] = defaultdict(dict)
        self.execution_trace: List[Dict[str, Any]] = []
        self.execution_units: List[ExecutionUnit] = []
        self.outputs: Dict[str, Any] = {}
        self._build_nodes()
        self._build_links()
        self._topo_order = self._topological_sort()

    def _build_nodes(self) -> None:
        for node_config in self.definition.get("nodes", []):
            node_type = node_config.get("type")
            if not node_type:
                raise GraphExecutionError(f"Node {node_config} has no type")
            try:
                node_cls = get_node(node_type)
            except KeyError as exc:
                raise GraphExecutionError(str(exc)) from exc
            node = node_cls(node_config)
            self.nodes[node.id] = node

    def _build_links(self) -> None:
        for raw_link in self.definition.get("links", []):
            link = Link(**raw_link)
            if link.to_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.to_node}")
            if link.from_node not in self.nodes:
                raise GraphExecutionError(f"Link references unknown node {link.from_node}")
            self.links.append(link)
            self.input_map[link.to_node][link.to_port] = link

    def _topological_sort(self) -> List[str]:
        # Kahn's algorithm
        dependencies: Dict[str, int] = {
            node_id: len(self.input_map.get(node_id, {})) for node_id in self.nodes
        }
        queue = deque([node_id for node_id, count in dependencies.items() if count == 0])
        order: List[str] = []

        children: Dict[str, List[str]] = defaultdict(list)
        for link in self.links:
            children[link.from_node].append(link.to_node)

        while queue:
            current = queue.popleft()
            order.append(current)
            for child in children.get(current, []):
                dependencies[child] -= 1
                if dependencies[child] == 0:
                    queue.append(child)

        if len(order) != len(self.nodes):
            raise GraphExecutionError("Graph contains a cycle or missing inputs")
        return order

    def _assign_device(self, node: NodeBase) -> str:
        hint = node.device_hint.lower() if isinstance(node.device_hint, str) else "auto"
        if hint in ("gpu", "cpu"):
            return hint
        if node.node_type.startswith("math"):
            return "gpu"
        return "cpu"

    def _build_execution_units(self) -> None:
        self.execution_units = []
        current_device: Optional[str] = None
        current_nodes: List[Dict[str, Any]] = []

        for node_id in self._topo_order:
            node = self.nodes[node_id]
            device = self._assign_device(node)
            if current_device is None or current_device != device:
                if current_nodes:
                    self.execution_units.append(ExecutionUnit(device=current_device, nodes=current_nodes))
                current_device = device
                current_nodes = []
            current_nodes.append({"id": node.id, "type": node.type})
        if current_nodes:
            self.execution_units.append(ExecutionUnit(device=current_device, nodes=current_nodes))

    def _gather_inputs(self, node_id: str, computed_values: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        node = self.nodes[node_id]
        if not node.input_ports:
            return {}
        if node_id not in self.input_map:
            raise GraphExecutionError(f"Node '{node_id}' declares inputs but no links are mapped")
        inputs: Dict[str, Any] = {}
        for port in node.input_ports:
            link = self.input_map[node_id].get(port)
            if not link:
                raise GraphExecutionError(f"Node '{node_id}' is missing link for port '{port}'")
            if link.from_node not in computed_values:
                return None
            value = computed_values[link.from_node].get(link.from_port)
            inputs[port] = value
        return inputs

    def run(self) -> Dict[str, Any]:
        self._build_execution_units()
        computed_values: Dict[str, Dict[str, Any]] = {}

        for node_id in self._topo_order:
            node = self.nodes[node_id]
            device = self._assign_device(node)
            inputs = self._gather_inputs(node_id, computed_values)
            if inputs is None:
                raise GraphExecutionError(f"Node '{node_id}' could not resolve inputs")
            ctx = ExecutionContext(device=device)
            outputs = node.forward(inputs, ctx)
            if set(outputs.keys()) != set(node.output_ports):
                raise GraphExecutionError(
                    f"Node '{node_id}' output ports {node.output_ports} do not match produced {list(outputs.keys())}"
                )
            computed_values[node_id] = outputs
            self.execution_trace.append(
                {
                    "node_id": node_id,
                    "type": node.type,
                    "device": device,
                    "outputs": outputs,
                    "logs": ctx.logger,
                }
            )

        self.outputs = self._collect_outputs(computed_values)
        return {
            "outputs": self.outputs,
            "trace": self.execution_trace,
            "units": [unit.__dict__ for unit in self.execution_units],
        }

    def _collect_outputs(self, computed_values: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        results: Dict[str, Any] = {}
        for entry in self.definition.get("output_nodes", []):
            node_id = entry["node_id"]
            port = entry["port"]
            alias = entry.get("alias", f"{node_id}.{port}")
            node_outputs = computed_values.get(node_id)
            if not node_outputs or port not in node_outputs:
                raise GraphExecutionError(f"Missing output for node '{node_id}' port '{port}'")
            results[alias] = node_outputs[port]
        if not results:
            # fallback to expose everything if output list not provided
            for node_id, output_map in computed_values.items():
                for port, value in output_map.items():
                    results[f"{node_id}.{port}"] = value
        return results

