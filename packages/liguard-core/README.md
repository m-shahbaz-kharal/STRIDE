# liguard-core

Core interfaces for LiGuard-Web node plugins.

## Installation

```bash
pip install liguard-core
```

## Usage

```python
from liguard_core import NodeBase, NodeSpec, PortSpec, register_node
from liguard_core.typesystem import t_string, t_int

MY_NODE_SPEC = NodeSpec(
    type="mypackage.mynode",
    version="1.0.0",
    display_name="My Node",
    category="Custom",
    inputs=[PortSpec(name="input", type=t_string())],
    outputs=[PortSpec(name="output", type=t_string())],
)

@register_node(MY_NODE_SPEC)
class MyNode(NodeBase):
    def forward(self, inputs, ctx):
        return {"output": inputs["input"].upper()}
```

## Creating a Plugin

1. Create a new package with `liguard-core` as a dependency
2. Define your nodes using `NodeSpec` and `@register_node`
3. Add an entry point in `pyproject.toml`:

```toml
[project.entry-points."liguard.plugins"]
myplugin = "my_plugin:register"
```
