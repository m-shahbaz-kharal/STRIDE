# LiGuard-Web Architecture Overview

This document provides a high-level overview of the LiGuard-Web system architecture.

## System Components

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Frontend (React)                           │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │   App.tsx   │  │  Dashboard  │  │   Graph     │  │   Domain   │ │
│  │   (Main)    │  │   Canvas    │  │   Editor    │  │   Layer    │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬─────┘ │
│         │                │                │                │       │
│         └────────────────┴────────────────┴────────────────┘       │
│                                   │                                 │
│                          React Flow + Hooks                         │
└─────────────────────────────────────────────────────────────────────┘
                                   │
                            WebSocket / HTTP
                                   │
┌─────────────────────────────────────────────────────────────────────┐
│                          Backend (FastAPI)                          │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌────────────┐ │
│  │   Runner    │  │  Executor   │  │   Domain    │  │   Nodes    │ │
│  │   (API)     │  │  (Engine)   │  │   Layer     │  │ (Registry) │ │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └──────┬─────┘ │
│         │                │                │                │       │
│         └────────────────┴────────────────┴────────────────┘       │
│                                   │                                 │
│                          Python + asyncio                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Directory Structure

```
LiGuard-Web/
├── backend/
│   ├── app/
│   │   ├── domain/           # Core domain models
│   │   │   ├── graph.py      # GraphDefinition (immutable)
│   │   │   ├── execution.py  # ExecutionState (mutable)
│   │   │   └── types.py      # Type system
│   │   ├── executor/         # Execution engine
│   │   │   ├── scheduler.py  # Ready-queue scheduling
│   │   │   ├── events.py     # Event emission
│   │   │   ├── completion.py # Task completion handling
│   │   │   └── streaming.py  # Main orchestrator
│   │   ├── nodes/            # Node implementations
│   │   └── runner.py         # API endpoints
│   └── tests/
│       └── test_execution/   # Execution engine tests
│
├── frontend/
│   ├── src/
│   │   ├── domain/           # Domain layer
│   │   │   ├── types.ts      # Type compatibility
│   │   │   └── graph-utils.ts # Graph algorithms
│   │   ├── components/       # React components
│   │   ├── hooks/            # React hooks
│   │   └── App.tsx           # Main application
│   └── package.json
│
└── docs/
    ├── architecture/         # Architecture documentation
    └── nodes/                # Node authoring guides
```

## Key Architectural Decisions

### 1. Separation of Graph Definition and Execution State

The system separates immutable graph structure from mutable execution state:

- **GraphDefinition**: Describes the graph structure (nodes, links, specs). Immutable once created. Safe to share across executions.
- **ExecutionState**: Tracks per-execution state (computed values, node status, trace). Mutable, isolated per execution run.

This separation enables:
- Safe graph reuse without state leakage
- Clear ownership of mutable state
- Easier testing with deterministic inputs

### 2. Ready-Queue Scheduling

Execution uses a ready-queue scheduler rather than recursive traversal:

```
┌──────────────────────────────────────────────┐
│             ReadyQueueScheduler              │
├──────────────────────────────────────────────┤
│  Ready Queue: [A, B, C]                      │
│  In Progress: {D, E}                         │
│  Completed:   {F, G, H}                      │
│                                              │
│  mark_node_complete(node_id)                 │
│    -> Returns newly ready dependents         │
│                                              │
│  mark_node_failed(node_id)                   │
│    -> Returns nodes to skip (dependents)     │
└──────────────────────────────────────────────┘
```

Benefits:
- Enables parallel execution of independent branches
- Explicit dependency tracking
- Clean failure propagation

### 3. Event-Driven Streaming

Execution progress is communicated via typed events:

```
Frontend                    Backend
   │                           │
   │   WS: start_execution     │
   │ ─────────────────────────>│
   │                           │
   │   EVENT: execution_start  │
   │ <─────────────────────────│
   │                           │
   │   EVENT: node_started     │
   │ <─────────────────────────│
   │                           │
   │   EVENT: node_completed   │
   │ <─────────────────────────│
   │                           │
   │   EVENT: execution_done   │
   │ <─────────────────────────│
```

### 4. Domain Layer Pattern

Both frontend and backend have a domain layer containing:
- Type definitions and compatibility rules
- Graph traversal algorithms
- Pure functions without I/O

This enables:
- Consistent behavior between frontend and backend
- Easy unit testing
- Clear separation from UI/API concerns

## Data Flow

### Graph Execution Flow

```
1. User triggers execution
        │
        ▼
2. Frontend builds execution payload
   (nodes, links, target nodes)
        │
        ▼
3. Backend receives request
        │
        ▼
4. GraphDefinition created from payload
        │
        ▼
5. ExecutionState initialized
        │
        ▼
6. Scheduler computes initial ready queue
        │
        ▼
7. Execute ready nodes (parallel where possible)
        │
        ├──> Node completes: mark complete, enqueue dependents
        │
        └──> Node fails: propagate failure to dependents
        │
        ▼
8. Stream events to frontend
        │
        ▼
9. Frontend updates UI state
```

### Type Compatibility Flow

```
1. User drags connection from output port
        │
        ▼
2. Frontend normalizes source type
        │
        ▼
3. For each potential target port:
   - Normalize target type
   - Check areTypesCompatible(source, target)
        │
        ▼
4. Display compatible ports as valid drop targets
```

## Component Responsibilities

### Backend Components

| Component | Responsibility |
|-----------|---------------|
| `runner.py` | HTTP/WebSocket endpoints, request handling |
| `executor/scheduler.py` | Ready-queue management, dependency tracking |
| `executor/events.py` | Event creation and emission |
| `executor/completion.py` | Node completion and failure propagation |
| `executor/streaming.py` | Execution orchestration |
| `domain/graph.py` | Immutable graph structure |
| `domain/execution.py` | Mutable execution state |
| `domain/types.py` | Type system and compatibility |

### Frontend Components

| Component | Responsibility |
|-----------|---------------|
| `App.tsx` | State management, hook composition |
| `DashboardCanvas.tsx` | Layout, viewport, drag handling |
| `BlueprintNode.tsx` | Node rendering, parameter UI |
| `domain/types.ts` | Type normalization, compatibility |
| `domain/graph-utils.ts` | Graph traversal algorithms |
| `hooks/useConnectionValidation.ts` | Connection validation logic |

## See Also

- [Execution Engine](./execution-engine.md) - Detailed execution flow
- [Type System](./type-system.md) - Port types and compatibility
- [Node Authoring Guide](../nodes/authoring-guide.md) - Creating new nodes
