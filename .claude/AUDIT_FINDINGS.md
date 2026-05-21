# STRIDE Audit — Findings

Branch: `audit-and-fixes`  Baseline tests: 232 passed / 2 warnings.

Severity legend:
- **P0** — correctness, security, data-loss, or crash bugs
- **P1** — significant bug, broken feature, major performance issue
- **P2** — minor bug, observability gap, small perf issue
- **P3** — polish, doc, style

---

## Backend runtime

### B-001 (P1) — ExecutionCache has no eviction; grows forever
`backend/app/execution.py:113`. Class-level `_cache` / `_metadata` dicts are
shared across every run process-wide and never evicted. After thousands of
runs (or one run with thousands of distinct inputs) memory grows linearly.
**Fix**: introduce an LRU cap (size in entries + bytes), with a
configurable env var.

### B-002 (P1) — `_cache` key truncated to 16 hex chars (64 bits)
`backend/app/execution.py:221`. Birthday collision at ~4 billion entries
becomes realistic; with adversarial input, even sooner. Combined with
B-001 unbounded growth, two distinct inputs could share a slot and serve
the wrong cached output. **Fix**: keep at least 32 hex chars (128 bit).

### B-003 (P1) — Unknown-type cache key falls back to `repr(value)`
`backend/app/execution.py:210`. Many Python objects have non-deterministic
`repr` (`<X at 0xDEADBEEF>`); two equal-valued objects yield different
cache keys → no dedupe; same object across runs likely different address.
**Fix**: require nodes to mark unhashable inputs as
`cache_policy="disabled"` and refuse to cache when the normalizer hits the
fallback, or hash via `id()` consistently for the run and bust on run end.

### B-004 (P0) — `force-abandon` of a node leaks a running thread
`backend/app/executor/streaming.py:107` and around 850. When
`_await_with_interruption_check` raises CancelledError after the
`_FORCE_ABANDON_TIMEOUT`, the underlying ThreadPoolExecutor thread keeps
running and continues writing to shared state (cache, computed_values,
etc.) after the executor "moves on". The pool is then shut down with
`wait=False`. Result: stray thread can race with the next graph run and
write into the global cache.
**Fix**: hold thread-pool reference in a list, drain on next run start;
mark abandoned node-ids and ignore their cache writes; or call
`shutdown(wait=True)` in the finally block.

### B-005 (P2) — `outputs = {k: outputs[k] for k in expected}` swallows extras
`backend/app/executor/node_execution.py:326`. If a node returns extra
keys (e.g. a typo in spec), they are dropped silently and the bug is
invisible. **Fix**: log a warning when the trim discards any key.

### B-006 (P2) — `node_status` writes outside `state_lock`
`backend/app/runner.py:288` `self._node_status[node_id] = result.status`.
Dict ops are not atomic across threads in PyPy/free-threading builds; in
CPython today they are atomic per-key, but the dict size mutation is not.
**Fix**: wrap in `state_lock`.

### B-007 (P2) — `execution_trace.append()` outside `state_lock`
Same finalize path. List append is atomic in CPython today but not
documented contract. **Fix**: lock.

### B-008 (P1) — Loop body progress accounting overflows on re-runs
`backend/app/executor/streaming.py:912`. If a node is re-run (re-entered
streaming loop) `progress_state["total"]` keeps being incremented with
no offsetting decrement when a loop short-circuits. Reported progress
can exceed 100 % or stay <100 % after completion.
**Fix**: track the per-loop adjustment and roll it back on early-break,
or compute progress as `min(completed/total, 1)` at the consumer.

### B-009 (P2) — bare `except Exception: pass` swallows real errors
Multiple sites across runner.py and main.py. Resource close, ws send, etc.
Reduces debuggability. **Fix**: log the exception at DEBUG.

### B-010 (P3) — `@app.on_event("startup")` is deprecated
`backend/app/main.py:107`. Confirmed by pytest warning. **Fix**: migrate
to FastAPI `lifespan=` context manager.

---

## FastAPI / API surface

### A-001 (P0) — WebSocket and run endpoints lack auth
`backend/app/main.py:166,183,200,217,251,280,289,323`. The graphs router
is auth-protected (need to confirm) but the executor endpoints, cache
endpoints, stream-frame endpoint, and the `/ws/run-graph` WebSocket are
fully open. Anyone reaching the server can run arbitrary graphs (which
means: download models, hit FL511, run YOLO, exhaust CPU/RAM, etc.).
**Fix**: gate behind auth dependency; add per-IP rate limits.

### A-002 (P0) — No CORS configuration
`backend/app/main.py`. Production frontends served on a different origin
than the API will silently fail. **Fix**: add explicit allowed origins
list, configurable via env.

### A-003 (P1) — No request-body size limit on `/api/run-graph` etc.
A 1 GB JSON POST will be parsed into memory before any validation runs.
**Fix**: middleware that aborts requests >N MB.

### A-004 (P1) — WebSocket accepts unbounded request concurrency
`backend/app/main.py:423`. One client can submit thousands of
`run_graph` requests in a tight loop; each spawns a new task that may
allocate threadpools and downloads. **Fix**: cap concurrent requests
per socket; drop or 429.

### A-005 (P1) — `websocket.receive_text()` has no size limit
A malicious client sending many GB of "graph JSON" will OOM the server.
**Fix**: explicit message-size cap.

### A-006 (P2) — `json.loads(data)` raises but error path swallows it
`backend/app/main.py:425`. If `data` is invalid JSON, exception
propagates and the entire WebSocket loop exits — connection dies with
no diagnostic to client. **Fix**: try/except, send structured error,
keep the loop alive.

### A-007 (P2) — `serve_client` route shadows static asset paths
`backend/app/main.py:112`. The wildcard could end up colliding with
SPA fallback patterns; acceptable but worth verifying.

### A-008 (P1) — Cache-clear endpoints lack auth and rate limit
Combined with A-001: any client can `/api/cache/clear` repeatedly to
defeat caching and burn compute.

### A-009 (P2) — `_json_serializer` falls back to `str(obj)`
`backend/app/main.py:88`. Silently produces lossy output. Better to
raise so the caller knows their type is not JSON-compatible.

---

## Frontend

(Findings will be added after frontend audit.)

---

## Plugin packages

(Findings will be added after package audit.)

---

## Scalability

### S-001 (P1) — Per-WebSocket-message task is unbounded
See A-004. Combined with the unbounded ThreadPoolExecutor per executor,
this is a clear way to exhaust both threads and memory.

### S-002 (P1) — `event_queue: asyncio.Queue()` has no maxsize
`backend/app/executor/streaming.py:704`. A slow client / paused tab can
cause infinite buffer growth. **Fix**: bounded queue + drop-policy or
backpressure.

### S-003 (P2) — `os.cpu_count()+2` per-executor default
On a 64-core box that's 66 threads per run × N concurrent runs. **Fix**:
cap to e.g. 8 by default, configurable per-graph via options.

### S-004 (P2) — `serialize_event` serialises full `outputs` dict for every event
Large outputs (10 MB pointclouds, big tensors) are repeatedly sent.
Streaming events include the full result. Frontend WS message size will
balloon for vision graphs. **Fix**: emit "completed" without the full
output, let UI request via a separate REST endpoint or via the final
`result` event.
