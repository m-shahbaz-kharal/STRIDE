import asyncio
import time
import sys
import os

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.runner import GraphExecutor
from app.nodes import time_random_nodes

# Define a graph with Start -> Delay A, Start -> Delay B
GRAPH_DEFINITION = {
    "nodes": [
        {"id": "start", "type": "core.time.now"},
        {"id": "delay_a", "type": "core.time.delay", "params": {"seconds": 1.0}},
        {"id": "delay_b", "type": "core.time.delay", "params": {"seconds": 1.0}}
    ],
    "links": [
        {"from_node": "start", "from_port": "timestamp", "to_node": "delay_a", "to_port": "passthrough"},
        {"from_node": "start", "from_port": "timestamp", "to_node": "delay_b", "to_port": "passthrough"}
    ]
}

async def run_partial_graph(label, entry_node):
    print(f"[{label}] Starting from {entry_node}...")
    
    options = {
        "mode": "from_node",
        "entry_nodes": [entry_node],
        "max_workers": 4
    }
    
    executor = GraphExecutor(GRAPH_DEFINITION, options=options)
    
    start_time = time.time()
    events = []
    async for event in executor.run_streaming():
        events.append(event.event_type)
        if event.event_type == "node_started" and event.node_id == entry_node:
             print(f"[{label}] {entry_node} STARTED running")
    
    end_time = time.time()
    duration = end_time - start_time
    print(f"[{label}] Finished in {duration:.2f}s")
    return duration

async def main():
    print("Testing parallel execution of PARTIAL runs (Run from Node)...")
    
    t0 = time.time()
    
    # Run Delay A and Delay B concurrently
    task1 = asyncio.create_task(run_partial_graph("Run A", "delay_a"))
    task2 = asyncio.create_task(run_partial_graph("Run B", "delay_b"))
    
    await asyncio.gather(task1, task2)
    
    total_time = time.time() - t0
    print(f"Total Wall Time: {total_time:.2f}s")
    
    # Ideally should correspond to max(1, 1) + overhead, so ~1-1.2s.
    # If serial, ~2s.
    if total_time < 1.5:
        print("SUCCESS: Partial runs executed in parallel.")
    else:
        print("FAILURE: Partial runs executed serially.")

if __name__ == "__main__":
    asyncio.run(main())
