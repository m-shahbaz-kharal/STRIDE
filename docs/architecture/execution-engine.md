# Execution Engine

This document describes how graphs are executed in LiGuard-Web.

## Overview

The execution engine processes node graphs using a ready-queue scheduler that enables parallel execution of independent branches while maintaining correct dependency order.

## Core Components

### 1. GraphDefinition

Immutable representation of the graph structure:

```python
@dataclass(frozen=True)
class NodeSpec:
    id: str
    type: str
    params: Dict[str, Any]
    position: Tuple[float, float]

@dataclass(frozen=True)
class LinkSpec:
    from_node: str
    from_port: str
    to_node: str
    to_port: str
    kind: str  # "data" or "control"

@dataclass
class GraphDefinition:
    nodes: Dict[str, NodeSpec]
    links: List[LinkSpec]
    input_map: Dict[str, Dict[str, LinkSpec]]   # node_id -> port -> link
    dependents: Dict[str, List[str]]            # node_id -> dependent nodes
    control_inputs: Dict[str, List[str]]        # node_id -> control sources
```

### 2. ExecutionState

Mutable per-execution state:

```python
@dataclass
class ExecutionState:
    execution_id: str
    computed_values: Dict[str, Dict[str, Any]]  # node_id -> port -> value
    node_status: Dict[str, NodeStatus]          # PENDING, RUNNING, COMPLETED, etc.
    execution_trace: List[NodeExecutionResult]
    variables: Dict[str, Any]                   # Shared state
    loop_context: Optional[LoopContext]
```

### 3. ReadyQueueScheduler

Manages which nodes are ready to execute:

```python
class ReadyQueueScheduler:
    def compute_initial_ready_queue(self) -> Deque[str]:
        """Find all nodes with no pending dependencies."""

    def mark_node_complete(self, node_id: str) -> List[str]:
        """Mark node complete, return newly ready dependents."""

    def mark_node_failed(self, node_id: str) -> List[str]:
        """Mark node failed, return dependents to skip."""

    def get_next_ready(self) -> Optional[str]:
        """Get next node to execute."""
```

## Execution Flow

### Phase 1: Initialization

```
┌─────────────────────────────────────────────────────────────┐
│                     Initialization                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Parse request payload                                   │
│     - Extract nodes, links, target nodes                    │
│                                                             │
│  2. Create GraphDefinition                                  │
│     - Build input_map (which ports connect where)           │
│     - Build dependents map (who depends on whom)            │
│     - Identify control flow edges                           │
│                                                             │
│  3. Initialize ExecutionState                               │
│     - Set all nodes to PENDING status                       │
│     - Initialize empty computed_values                      │
│     - Generate execution_id                                 │
│                                                             │
│  4. Compute execution set                                   │
│     - If running all: include all nodes                     │
│     - If running selection: include selected + dependencies │
│     - Apply cache optimization                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Phase 2: Ready Queue Computation

```
┌─────────────────────────────────────────────────────────────┐
│                 Ready Queue Computation                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  For each node in execution_set:                            │
│    If all input sources are:                                │
│      - Outside execution set, OR                            │
│      - Already completed                                    │
│    Then: Add to ready queue                                 │
│                                                             │
│  Example:                                                   │
│                                                             │
│    A ──> B ──> C                                            │
│    │           │                                            │
│    └───> D ────┘                                            │
│                                                             │
│  Initial ready queue: [A]                                   │
│  After A completes:   [B, D]  (parallel)                    │
│  After B, D complete: [C]                                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Phase 3: Node Execution

```
┌─────────────────────────────────────────────────────────────┐
│                    Node Execution                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  While ready_queue not empty OR tasks in progress:          │
│                                                             │
│    1. Get next ready node                                   │
│       - Check concurrency limit                             │
│       - Prioritize by level (lower first)                   │
│                                                             │
│    2. Gather inputs                                         │
│       - For each input port:                                │
│         - Find source via input_map                         │
│         - Get value from computed_values                    │
│                                                             │
│    3. Execute node                                          │
│       - Look up node handler by type                        │
│       - Call execute(params, inputs)                        │
│       - Handle async/generator nodes                        │
│                                                             │
│    4. Store outputs                                         │
│       - Save to computed_values[node_id]                    │
│       - Update node_status to COMPLETED                     │
│                                                             │
│    5. Emit events                                           │
│       - node_started when execution begins                  │
│       - node_completed with outputs                         │
│       - node_error if failed                                │
│                                                             │
│    6. Update scheduler                                      │
│       - mark_node_complete(node_id)                         │
│       - Add returned nodes to ready queue                   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### Phase 4: Completion

```
┌─────────────────────────────────────────────────────────────┐
│                      Completion                             │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Wait for all in-progress tasks                          │
│                                                             │
│  2. Build execution summary                                 │
│     - Total nodes executed                                  │
│     - Success/failure counts                                │
│     - Execution time                                        │
│                                                             │
│  3. Emit execution_done event                               │
│                                                             │
│  4. Clean up resources                                      │
│     - Cancel pending tasks                                  │
│     - Close connections                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Control Flow Handling

### For Loop

```
┌─────────────────────────────────────────────────────────────┐
│                       For Loop                              │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Structure:                                                 │
│    ForLoop node with:                                       │
│      - Input: iterable                                      │
│      - Body: contained nodes                                │
│      - Output: collected results                            │
│                                                             │
│  Execution:                                                 │
│    for item in iterable:                                    │
│      1. Set loop variable to item                           │
│      2. Execute body nodes in topological order             │
│      3. Collect body outputs                                │
│    Aggregate results                                        │
│                                                             │
│  Events:                                                    │
│    - loop_iteration_start (iteration index)                 │
│    - loop_iteration_end (iteration outputs)                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### If/Else

```
┌─────────────────────────────────────────────────────────────┐
│                       If/Else                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Structure:                                                 │
│    IfElse node with:                                        │
│      - Input: condition (boolean)                           │
│      - Then branch: nodes to execute if true                │
│      - Else branch: nodes to execute if false               │
│                                                             │
│  Execution:                                                 │
│    1. Evaluate condition                                    │
│    2. If true: execute then_branch nodes                    │
│    3. If false: execute else_branch nodes                   │
│    4. Skip inactive branch entirely                         │
│                                                             │
│  Note: Nodes in skipped branch get SKIPPED status           │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Parallel Execution

Independent branches execute concurrently:

```
      A
     / \
    B   C     <- B and C execute in parallel
     \ /
      D       <- D waits for both B and C
```

Concurrency is controlled by `max_workers` parameter:

```python
scheduler = ReadyQueueScheduler(
    execution_set=nodes,
    max_workers=4,  # Max 4 nodes executing simultaneously
    ...
)
```

## Error Handling

### Error Propagation

When a node fails:

```
1. Node A fails with error
        │
        ▼
2. Scheduler marks A as FAILED
        │
        ▼
3. Get all dependents of A (transitive)
        │
        ▼
4. Mark dependents as SKIPPED
   (they won't execute)
        │
        ▼
5. Continue with independent branches
```

### Error Isolation

Failures don't affect independent branches:

```
    A
   / \
  B   C   <- If B fails, C still executes
   \ /
    D     <- D is skipped (depends on B)
    |
    E     <- E is skipped (depends on D)
```

## Caching

The execution engine supports caching computed values:

```python
# Check if node result is cached
if cache.has(node_id, input_hash):
    result = cache.get(node_id, input_hash)
    # Skip execution, use cached result
else:
    result = execute_node(node)
    cache.set(node_id, input_hash, result)
```

Cache invalidation:
- When node parameters change
- When any upstream node re-executes
- When explicitly cleared by user

## Events

The execution engine emits these event types:

| Event | Description |
|-------|-------------|
| `execution_start` | Execution begins, includes plan |
| `node_started` | Node execution begins |
| `node_completed` | Node finished successfully |
| `node_error` | Node failed with error |
| `node_skipped` | Node skipped due to upstream failure |
| `loop_iteration_start` | Loop iteration begins |
| `loop_iteration_end` | Loop iteration completes |
| `execution_done` | Execution finished |

Event structure:

```python
{
    "type": "node_completed",
    "node_id": "abc123",
    "outputs": {"result": 42},
    "execution_time_ms": 150
}
```

## See Also

- [Architecture Overview](./overview.md)
- [Type System](./type-system.md)
