# LiGuard-Web Backend

FastAPI-based execution engine for visual node graphs.

## Architecture

```
app/
├── main.py              # FastAPI application & routes
├── runner.py            # GraphExecutor - core execution engine
├── execution.py         # Execution primitives (events, results, stats)
├── node_spec.py         # NodeSpec, PortSpec type definitions
├── typesystem.py        # Re-exports from liguard_core
├── executor/            # Modular execution components
│   ├── __init__.py      # Package exports
│   └── cancellation.py  # CancellationController
└── nodes/               # Node implementations
    ├── __init__.py      # Node registry & registration
    ├── base.py          # NodeBase, ExecutionContext
    ├── primitives.py    # Number, Boolean, String constants
    ├── math.py          # Arithmetic operations
    ├── utilities.py     # String, Array, JSON, Debug nodes
    ├── programming.py   # Control flow nodes
    └── ...
```

## Key Components

### GraphExecutor (`runner.py`)

The main execution engine that:
- Builds execution graph from JSON definition
- Performs topological sort for execution order
- Computes execution levels for parallelization
- Handles loops, if/else branches, and control flow
- Manages caching and cancellation

```python
from app.runner import GraphExecutor

executor = GraphExecutor(graph_definition)
result = executor.run()  # Synchronous execution

# Or streaming execution
async for event in executor.run_streaming():
    print(event.event_type, event.node_id)
```

### CancellationController (`executor/cancellation.py`)

Thread-safe cancellation management:
- Global cancellation via `cancel_all()`
- Per-node cancellation via `cancel_node(node_id)`
- Running task registration for forced termination

### Node Registration

Nodes are registered using decorators:

```python
from app.nodes import register_node
from app.nodes.base import NodeBase, ExecutionContext
from app.node_spec import NodeSpec, PortSpec

MY_NODE_SPEC = NodeSpec(
    type="my.custom.node",
    version="1.0.0",
    display_name="My Node",
    inputs=[PortSpec(name="input", type=t_float())],
    outputs=[PortSpec(name="result", type=t_float())],
)

@register_node(MY_NODE_SPEC)
class MyNode(NodeBase):
    def forward(self, inputs: dict, ctx: ExecutionContext) -> dict:
        return {"result": inputs["input"] * 2}
```

## API Routes

### Graph Execution

- `POST /api/run-graph` - Execute graph synchronously
- `POST /api/run-graph-async` - Execute with async/await
- `WS /ws/run-graph` - Execute with streaming events

### Execution Control

- `POST /api/executions/{id}/cancel` - Cancel entire execution
- `POST /api/executions/{id}/cancel/{node}` - Cancel specific node

### Cache Management

- `GET /api/cache/size` - Get cache entry count
- `POST /api/cache/clear` - Clear all cache entries
- `POST /api/cache/clear-nodes` - Clear cache for specific nodes

### Node Definitions

- `GET /api/node-definitions` - Get all registered node types

## Testing

```bash
uv run pytest tests/ -v
```

Test files:
- `tests/conftest.py` - Shared fixtures
- `tests/test_executor.py` - GraphExecutor tests
- `tests/test_cancellation.py` - CancellationController tests
