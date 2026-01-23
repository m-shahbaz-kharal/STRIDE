# LiGuard-Web Frontend

React-based visual graph editor for node pipelines.

## Architecture

```
src/
├── App.tsx                   # Main application component
├── api.ts                    # API client functions
├── types.ts                  # TypeScript type definitions
├── components/
│   ├── graph/
│   │   ├── BlueprintNode.tsx # Custom node component
│   │   ├── CustomEdge.tsx    # Custom edge rendering
│   │   └── TypeAwareConnectionLine.tsx
│   ├── layout/
│   │   └── AppHeader.tsx     # Top navigation bar
│   ├── NodePalette.tsx       # Node type browser/search
│   ├── NodeInspector.tsx     # Selected node properties
│   ├── LogPanel.tsx          # Execution logs viewer
│   └── DisplayView.tsx       # Output display dashboard
├── hooks/
│   ├── useGraphExecution.ts  # WebSocket graph execution
│   ├── useNodeLibrary.ts     # Node definitions from backend
│   ├── useConnectionValidation.ts # Type-safe connections
│   ├── useUndoRedo.ts        # Graph state history
│   ├── usePanelResize.ts     # Resizable side panels
│   ├── useSmartConnect.ts    # Smart node connection
│   └── useKeyboardShortcuts.ts
└── graph/
    └── utils.ts              # Graph utility functions
```

## Key Hooks

### useGraphExecution

WebSocket-based execution with streaming events:

```tsx
const {
  isConnected,    // WebSocket connection status
  isRunning,      // Execution in progress
  hasRunningNodes,// Any nodes currently running
  nodeStatuses,   // Map of node ID -> status
  trace,          // Execution trace entries
  progress,       // 0-1 completion progress
  executionId,    // Current execution ID
  runGraph,       // Start execution
} = useGraphExecution();
```

### useNodeLibrary

Fetches and caches available node types:

```tsx
const { nodeLibrary } = useNodeLibrary();
// nodeLibrary: NodeTypeDefinition[]
```

### useConnectionValidation

Type-safe port connection validation:

```tsx
const {
  arePortTypesCompatible,  // Check type compatibility
  getPortTypeForHandle,    // Get port type info
  validateConnection,      // Full connection validation
} = useConnectionValidation({ nodes, connectStartParams });
```

## Component Props

### BlueprintNode

Custom ReactFlow node with:
- Typed input/output ports with colored handles
- Inline input fields for unconnected ports
- Execution status indicators (running, completed, error)
- Node actions (run, cache, interrupt, delete)

### AppHeader

Top navigation with:
- Tab switching (Home, Graph Editor, Display)
- Execution controls (Run, Stop, Clear Cache)
- Graph save/rename
- Connection status indicator

## Development

```bash
npm install     # Install dependencies
npm run dev     # Start dev server with HMR
npm run build   # Production build
npm run lint    # TypeScript/ESLint checks
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_URL` | (dev proxy) | Backend API base URL |
