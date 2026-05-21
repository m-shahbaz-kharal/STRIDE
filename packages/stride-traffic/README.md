# stride-traffic

Traffic and transportation engineering nodes for STRIDE.

This plugin package adds a comprehensive library of nodes for analysing
roadway video, building traffic flow / speed / safety / crash metrics,
and producing reports that match the metrics transportation agencies
and academic researchers actually use.

## Categories

- **traffic.calibration.*** — vanishing-point detection, ground-plane
  homography, pixel-to-world projection, scale calibration. Produces
  a shared `traffic.calibration` record consumed by every downstream
  node.
- **traffic.roi.*** — virtual lines, polygons, lane definitions,
  point-in-polygon helpers, ROI overlay annotators.
- **traffic.count.*** — line-crossing counters, polygon enter/exit
  counters, lane-bin counters, FHWA classification counters.
- **traffic.flow.*** — AADT extrapolation, peak-hour factor, density
  (k = q/v), saturation flow, capacity (HCM v/c), time-mean and
  space-mean speed.
- **traffic.speed.*** — per-track instantaneous speed, percentile
  speeds, speed-flow-density fundamental diagrams, free-flow speed.
- **traffic.trajectory.*** — Savitzky-Golay smoothing, accumulator,
  acceleration profiles, lane-assignment, lane-change detection,
  stop detection, resampling.
- **traffic.safety.*** — TTC, mTTC, PET, DRAC, headway, near-miss
  events, conflict-severity classification, KABCO mapping.
- **traffic.events.*** — stopped vehicle, wrong-way driving,
  pedestrian-on-roadway, queue length, queue spillback, hard-braking,
  illegal turn, debris detection.
- **traffic.intersection.*** — turn-movement counter, control delay,
  HCM Level-of-Service, queue-length-by-time-bin, intersection
  capacity utilisation.
- **traffic.pedestrian.*** — pedestrian count, conflict, wait-time,
  walking-speed, group detection, bike-lane intrusion.
- **traffic.report.*** — time-bin aggregation, peak-hour, travel-time
  reliability indices, percentiles, CSV/JSON snapshot writer.
- **traffic.crash.*** — Highway Safety Manual (HSM) Safety Performance
  Functions, Empirical Bayes adjustment, Crash Modification Factors,
  network-screening, KABCO/EPDO cost weights.

## References

- *Highway Capacity Manual* (HCM 6th edition / 7th edition).
- *Highway Safety Manual* (HSM 1st edition + Supplement).
- FHWA, *Surrogate Safety Assessment Model (SSAM)* — Pu & Joshi, 2008.
- Hayward, J. C., *Near-Miss Determination Through Use of a Scale of
  Danger* (1972) — TTC.
- Allen, B. L., et al., *Analysis of traffic conflicts and collisions*
  (1978) — PET.
- Zhang, Y., et al., *ByteTrack* — ECCV 2022.
- Weng, X., Kitani, K., *AB3DMOT* — IROS 2020.

## Quick start

```bash
cd backend
uv sync
uv run python scripts/seed_demo_graphs.py
uv run uvicorn app.main:app --reload --port 8000
```

Then open the frontend and pick any "Demo · Traffic …" graph.
