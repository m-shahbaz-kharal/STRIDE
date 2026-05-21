# Traffic / Transportation Engineering Plugin

The `stride-traffic` package adds 57 nodes covering the algorithms that
state DOTs, MPOs, and academic transportation researchers actually use.
It is detector-agnostic — the upstream YOLO/RT-DETR/ByteTrack stack
already lives in `stride-yolo`, `stride-rtdetr`, and `stride-bytetrack`,
so this package focuses on the *analysis* layer that transforms
detections + tracks into engineering-grade traffic metrics.

## Algorithm taxonomy

```
┌────────────────────────────────────────────────────────────────────┐
│                        stride-traffic                              │
├────────────────────────────────────────────────────────────────────┤
│  calibration/    intrinsic + ground-plane homography               │
│  roi/            virtual lines, polygons, lane regions             │
│  counting/       line-cross, polygon enter/exit, classification    │
│  flow/           AADT, PHF, density, v/c, sat-flow, fundamental    │
│  speed/          per-track speed, percentile (85th, 95th)          │
│  trajectory/     accumulator, acceleration, stop detect            │
│  safety/         TTC, PET, DRAC, headway                           │
│  events/         stopped, wrong-way, hard-brake, queue, merge      │
│  intersection/   turn-movement, control-delay, LOS, ICU            │
│  pedestrian/     filter, crossing-count, ped-vehicle conflict      │
│  report/         time-bin, percentile-bundle, TTI/PTI/BI, csv      │
│  crash/          SPF (HSM), CMF, Empirical-Bayes, PSI, EPDO        │
└────────────────────────────────────────────────────────────────────┘
```

## Wire forms

The package adds three new domain record kinds, all namespaced under
`traffic.*`:

| Kind | Purpose |
|---|---|
| `traffic.calibration` | Per-camera intrinsics + ground-plane homography. Consumed by every node that needs world-frame positions or speeds. |
| `traffic.line` | A directed line segment in image (pixel) coordinates. |
| `traffic.polygon` | A polygon ROI in image coordinates. |
| `traffic.event` | A discrete observable event (stopped, near-miss, wrong-way, hard-brake, queue, …). Uniform shape so the merge / report nodes can work with the union of detector outputs. |

See `packages/stride-traffic/src/stride_traffic/types.py` for the
canonical schemas; the Python helpers `make_calibration`, `make_line`,
`make_polygon`, and `make_event` produce wire-shape dicts.

## Conventions

* **Coordinates.** Pixel coordinates use the image-plane origin
  (top-left, y increases downwards). World coordinates are produced by
  the calibration's homography (or its `scale_m_per_px` fallback for
  camera setups without a perspective model).
* **Line direction.** A `traffic.line` records two endpoints `a` and
  `b`. The signed distance of a point from the line follows the
  standard cross-product convention: positive = LEFT of the directed
  line `(a -> b)`, negative = RIGHT. A track that crosses from positive
  to negative is counted as `forward`; the reverse is `backward`.
* **Track-store sharing.** Every node that needs per-track history
  (`speed.estimate`, `trajectory.accumulate`, `safety.ttc_pairwise`,
  `events.stopped_vehicle`, …) reads/writes a per-run track store keyed
  by an opaque `store_key` string. Wire multiple consumers to the same
  store_key when they share state; use distinct keys when they should
  see independent histories.
* **Stateful state.** All running counters, track stores, and
  background models live on `ExecutionContext` (per-run scope) — never
  on module-level dicts. Two consecutive runs always start fresh.

## References

* AASHTO, *Highway Capacity Manual* (HCM 6th / 7th ed.) — flow,
  density, v/c, control delay (Eq. 19-26), LOS bins (Exhibit 19-8).
* AASHTO, *Highway Safety Manual* (HSM 1st ed. + Supplement) — Part C
  predictive method, SPFs (Eq. 10-6 rural, Ch. 12 urban), EB
  adjustment, calibration factor C.
* FHWA SSAM (Pu & Joshi, 2008) — surrogate safety severity bins.
* Hayward, J. C. (1972) — TTC formulation.
* Allen, B. L. et al. (1978) — PET formulation.
* Husch, D. & Albeck, J. (2003) — Intersection Capacity Utilisation.
* AAA / FHWA NDS — 3.4 m/s² hard-brake threshold.
* Zhang, Y. et al., ECCV 2022 — ByteTrack (used upstream).
* Weng, X. & Kitani, K., IROS 2020 — AB3DMOT (3-D tracking, used by
  `stride-kalman`).

## Quick-start

### 1. Sync the package

```bash
cd backend
uv sync
```

### 2. Run the static smoke tests

```bash
uv run pytest tests/test_traffic_basic.py -v
```

(36 tests, runs in <0.5 s.)

### 3. Seed the demo graphs

```bash
uv run python scripts/seed_demo_graphs.py
```

This adds five new demos to the canonical seed list:

| Demo | Description |
|---|---|
| Traffic 01 — Flow Metrics | PHF / AADT / density / v/c / HCM control delay / LOS, all from literal inputs. Smoke test. |
| Traffic 02 — HSM Crash Prediction | Rural-2L + urban-arterial SPFs, CMFs, Empirical-Bayes, PSI, EPDO. Pure numeric. |
| Traffic 03 — Surrogate Safety | DRAC, PET, headway, travel-time reliability indices. Pure numeric. |
| Traffic 04 — Live Video Counting | FL511 stream → YOLO → ByteTrack → line counter + classifier. Live. |
| Traffic 05 — Live Speed Estimation | FL511 stream → YOLO → ByteTrack → speed.estimate → 85th-percentile summary. Live. |

### 4. Verify

```bash
# Static demos (no network / no weights):
uv run python scripts/verify_traffic_static.py

# Full WebSocket end-to-end (needs Postgres + the seeded user):
uv run python scripts/verify_demos_ws.py
```

## Building your own pipeline

A typical real-time traffic pipeline looks like:

```
fl511.connect ─┐
               ├─ fl511.get_frame ─ image.detect.yolo ─ tracker.bytetrack ─┐
               │                                                            │
                                                                            ├─ traffic.speed.estimate ─ traffic.speed.summary
                                                                            ├─ traffic.count.line     ─ traffic.report.event_summary
                                                                            └─ traffic.events.wrong_way
               (all wired into a core.control.for or core.control.while loop)
```

Then attach a `traffic.calibration.from_homography` (or `.from_known_width`
for the lazy version) and hand its output to every speed / safety / event
node that needs world-frame positions.

For static analysis (no video), the flow / crash / report / safety
modules can be wired directly with literal input values — see
`demo_traffic_01`, `demo_traffic_02`, and `demo_traffic_03` in
`backend/scripts/seed_demo_graphs.py` for working templates.

## See also

* `packages/stride-traffic/README.md` — package-level overview.
* `docs/nodes/authoring-guide.md` — how to add new nodes.
* `docs/architecture/type-system.md` — record kind / structural
  subtyping rules.
