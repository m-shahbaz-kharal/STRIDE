# Node Authoring Guide

This guide explains how to create new nodes for LiGuard-Web.

## Overview

Nodes are the building blocks of graphs. Each node:
- Has typed input and output ports
- Contains execution logic
- Can have configurable parameters

## Node Structure

### NodeSpec

Every node has a specification that describes its interface:

```python
@dataclass
class NodeSpec:
    id: str                     # Unique identifier
    type: str                   # Node type (e.g., "Math.Add")
    category: str               # Category for grouping
    label: str                  # Display name
    description: str            # Help text
    inputs: List[PortSpec]      # Input ports
    outputs: List[PortSpec]     # Output ports
    params: List[ParamSpec]     # Configurable parameters
```

### PortSpec

Ports define the node's inputs and outputs:

```python
@dataclass
class PortSpec:
    name: str                   # Port identifier
    type: TypeDescriptor        # Port type
    label: str                  # Display name
    description: str            # Help text
    default: Any = None         # Default value (inputs only)
    optional: bool = False      # Whether input is required
```

### ParamSpec

Parameters are user-configurable values:

```python
@dataclass
class ParamSpec:
    name: str                   # Parameter identifier
    type: str                   # Parameter type
    label: str                  # Display name
    default: Any                # Default value
    options: List[Any] = None   # For select/enum types
```

## Creating a Simple Node

### Step 1: Define the Node Handler

Create a new file or add to an existing category file in `backend/app/nodes/`:

```python
# backend/app/nodes/math_nodes.py

from app.nodes.base import NodeHandler, register_node

@register_node("Math.Multiply")
class MultiplyNode(NodeHandler):
    """Multiplies two numbers."""

    @classmethod
    def get_spec(cls) -> dict:
        return {
            "type": "Math.Multiply",
            "category": "Math",
            "label": "Multiply",
            "description": "Multiplies two numbers together",
            "inputs": [
                {
                    "name": "a",
                    "type": {"kind": "float"},
                    "label": "A",
                    "description": "First number",
                },
                {
                    "name": "b",
                    "type": {"kind": "float"},
                    "label": "B",
                    "description": "Second number",
                },
            ],
            "outputs": [
                {
                    "name": "result",
                    "type": {"kind": "float"},
                    "label": "Result",
                    "description": "Product of A and B",
                },
            ],
            "params": [],
        }

    def execute(self, inputs: dict, params: dict) -> dict:
        a = inputs.get("a", 0)
        b = inputs.get("b", 0)
        return {"result": a * b}
```

### Step 2: Register the Node

The `@register_node` decorator automatically registers the node. Ensure the module is imported in `backend/app/nodes/__init__.py`:

```python
# backend/app/nodes/__init__.py

from . import math_nodes  # Add this line if not present
```

### Step 3: Test the Node

Create a test file:

```python
# backend/tests/test_nodes/test_math_nodes.py

import pytest
from app.nodes.math_nodes import MultiplyNode

def test_multiply_basic():
    node = MultiplyNode()
    result = node.execute(
        inputs={"a": 3, "b": 4},
        params={}
    )
    assert result["result"] == 12

def test_multiply_with_zero():
    node = MultiplyNode()
    result = node.execute(
        inputs={"a": 5, "b": 0},
        params={}
    )
    assert result["result"] == 0
```

## Working with Types

### Simple Types

```python
# Integer input
{"name": "count", "type": {"kind": "int"}}

# Float input
{"name": "value", "type": {"kind": "float"}}

# String input
{"name": "text", "type": {"kind": "string"}}

# Boolean input
{"name": "enabled", "type": {"kind": "bool"}}
```

### Container Types

```python
# List of integers
{"name": "numbers", "type": {"kind": "list", "item": {"kind": "int"}}}

# Map with string values
{"name": "config", "type": {"kind": "map", "value": {"kind": "string"}}}

# Optional integer
{"name": "limit", "type": {"kind": "option", "item": {"kind": "int"}}}
```

### Special Types

```python
# Any type (accepts anything)
{"name": "data", "type": {"kind": "any"}}

# Control flow signal
{"name": "trigger", "type": {"kind": "control"}}

# Tensor with specific dtype
{"name": "weights", "type": {"kind": "tensor", "metadata": {"dtype": "float32"}}}
```

## Parameters

### Text Parameter

```python
{
    "name": "separator",
    "type": "string",
    "label": "Separator",
    "default": ","
}
```

### Number Parameter

```python
{
    "name": "precision",
    "type": "int",
    "label": "Decimal Places",
    "default": 2
}
```

### Select Parameter

```python
{
    "name": "operation",
    "type": "select",
    "label": "Operation",
    "default": "add",
    "options": ["add", "subtract", "multiply", "divide"]
}
```

### Boolean Parameter

```python
{
    "name": "case_sensitive",
    "type": "bool",
    "label": "Case Sensitive",
    "default": True
}
```

### Code Parameter

```python
{
    "name": "expression",
    "type": "code",
    "label": "Expression",
    "default": "x * 2"
}
```

## Async Nodes

For I/O-bound operations, use async execution:

```python
@register_node("Network.HttpGet")
class HttpGetNode(NodeHandler):
    @classmethod
    def get_spec(cls) -> dict:
        return {
            "type": "Network.HttpGet",
            # ... spec
        }

    async def execute_async(self, inputs: dict, params: dict) -> dict:
        import aiohttp

        url = inputs["url"]
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                text = await response.text()
                return {"body": text, "status": response.status}
```

## Generator Nodes (Streaming Output)

For nodes that produce incremental output:

```python
@register_node("LLM.Generate")
class GenerateNode(NodeHandler):
    @classmethod
    def get_spec(cls) -> dict:
        return {
            "type": "LLM.Generate",
            "outputs": [
                {"name": "text", "type": {"kind": "string"}, "streaming": True},
            ],
            # ... rest of spec
        }

    async def execute_streaming(self, inputs: dict, params: dict):
        prompt = inputs["prompt"]

        async for chunk in generate_text(prompt):
            yield {"text": chunk}
```

## Control Flow Nodes

### Loop Node

```python
@register_node("Control.ForEach")
class ForEachNode(NodeHandler):
    @classmethod
    def get_spec(cls) -> dict:
        return {
            "type": "Control.ForEach",
            "category": "Control",
            "control_type": "loop",
            "inputs": [
                {"name": "items", "type": {"kind": "list", "item": {"kind": "any"}}},
            ],
            "outputs": [
                {"name": "item", "type": {"kind": "any"}, "scope": "body"},
                {"name": "index", "type": {"kind": "int"}, "scope": "body"},
                {"name": "results", "type": {"kind": "list", "item": {"kind": "any"}}},
            ],
            "body": True,  # Indicates this node has a body scope
        }
```

### Conditional Node

```python
@register_node("Control.If")
class IfNode(NodeHandler):
    @classmethod
    def get_spec(cls) -> dict:
        return {
            "type": "Control.If",
            "category": "Control",
            "control_type": "conditional",
            "inputs": [
                {"name": "condition", "type": {"kind": "bool"}},
            ],
            "branches": ["then", "else"],  # Named branches
        }
```

## Error Handling

Raise exceptions to indicate errors:

```python
def execute(self, inputs: dict, params: dict) -> dict:
    divisor = inputs["divisor"]

    if divisor == 0:
        raise ValueError("Cannot divide by zero")

    return {"result": inputs["dividend"] / divisor}
```

The execution engine will:
1. Catch the exception
2. Mark the node as FAILED
3. Emit an error event
4. Skip dependent nodes

## Best Practices

### 1. Keep Nodes Focused

Each node should do one thing well:

```python
# Good: Single responsibility
class AddNode:      # Adds two numbers
class MultiplyNode: # Multiplies two numbers

# Bad: Too many responsibilities
class MathNode:     # Adds, subtracts, multiplies, divides...
```

### 2. Use Descriptive Types

Be specific with types to enable better validation:

```python
# Good: Specific type
{"kind": "list", "item": {"kind": "int"}}

# Less good: Generic type
{"kind": "any"}
```

### 3. Provide Sensible Defaults

```python
{
    "name": "timeout",
    "type": "int",
    "label": "Timeout (ms)",
    "default": 5000,  # Reasonable default
}
```

### 4. Document Parameters

```python
{
    "name": "regex",
    "type": "string",
    "label": "Pattern",
    "description": "Regular expression pattern (Python re syntax)",
    "default": ".*"
}
```

### 5. Handle Missing Inputs

```python
def execute(self, inputs: dict, params: dict) -> dict:
    # Use .get() with defaults
    value = inputs.get("value", 0)
    multiplier = inputs.get("multiplier", 1)

    return {"result": value * multiplier}
```

### 6. Validate Inputs

```python
def execute(self, inputs: dict, params: dict) -> dict:
    items = inputs.get("items", [])

    if not isinstance(items, list):
        raise TypeError(f"Expected list, got {type(items).__name__}")

    if len(items) == 0:
        raise ValueError("List cannot be empty")

    return {"first": items[0]}
```

## Testing Guidelines

### Unit Tests

Test node logic in isolation:

```python
def test_node_basic():
    node = MyNode()
    result = node.execute({"a": 1, "b": 2}, {})
    assert result["sum"] == 3

def test_node_with_params():
    node = MyNode()
    result = node.execute({"value": 10}, {"multiplier": 2})
    assert result["result"] == 20

def test_node_error_handling():
    node = MyNode()
    with pytest.raises(ValueError):
        node.execute({"divisor": 0}, {})
```

### Integration Tests

Test nodes within graph execution:

```python
def test_node_in_graph():
    graph = create_test_graph([
        {"id": "1", "type": "Math.Add", "params": {}},
        {"id": "2", "type": "Math.Multiply", "params": {}},
    ])

    result = execute_graph(graph, inputs={"a": 2, "b": 3})
    # Verify execution completed correctly
```

## See Also

- [Architecture Overview](../architecture/overview.md)
- [Type System](../architecture/type-system.md)
- [Execution Engine](../architecture/execution-engine.md)
