"""Reporting and aggregation nodes.

Time-bin aggregation, percentile / histogram emitters, travel-time
reliability indices, and snapshot writers (CSV / JSON to disk).
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import statistics
import time
from typing import Any, Dict, List, Optional

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError, NodeRuntimeError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_float,
    t_int,
    t_list,
    t_map,
    t_string,
)

from .types import is_event, t_traffic_event


# ---------------------------------------------------------------------------
# traffic.report.time_bin — bin a series into 15-min/hour/day windows
# ---------------------------------------------------------------------------


TIME_BIN_SPEC = NodeSpec(
    type="traffic.report.time_bin",
    version="1.0.0",
    display_name="Report · Time-bin Counts",
    category="Traffic Report",
    summary="Group event/crossing timestamps into fixed-width bins.",
    description=(
        "Given a list of timestamps (epoch seconds) and a bin width "
        "(seconds), returns a histogram of counts per bin. Use 900 s "
        "for 15-minute bins, 3600 s for hourly, 86400 s for daily."
    ),
    icon="bar-chart",
    tags=["traffic", "report", "aggregation"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="timestamps", type=t_list(t_float()), required=True),
        PortSpec(name="bin_width_s", type=t_float(), required=False, default=900.0,
                 constraints={"min": 1.0}),
        PortSpec(name="anchor_s", type=t_float(), required=False, default=0.0,
                 description="Bin alignment origin in epoch seconds"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="bins", type=t_list(t_int())),
        PortSpec(name="bin_starts_s", type=t_list(t_float())),
        PortSpec(name="total", type=t_int()),
        PortSpec(name="peak_bin", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(TIME_BIN_SPEC)
class ReportTimeBinNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        ts = sorted(float(t) for t in (inputs.get("timestamps") or []) if t is not None)
        bin_w = float(inputs.get("bin_width_s") or 900.0)
        anchor = float(inputs.get("anchor_s") or 0.0)
        if not ts or bin_w <= 0:
            return {
                "control_out": None,
                "bins": [], "bin_starts_s": [],
                "total": 0, "peak_bin": 0,
            }
        first = ts[0]
        last = ts[-1]
        # Align bin starts to multiples of bin_w from the anchor.
        first_bin_start = anchor + math.floor((first - anchor) / bin_w) * bin_w
        last_bin_start = anchor + math.floor((last - anchor) / bin_w) * bin_w
        n_bins = int(math.floor((last_bin_start - first_bin_start) / bin_w)) + 1
        bins = [0] * n_bins
        for t in ts:
            idx = int(math.floor((t - first_bin_start) / bin_w))
            if 0 <= idx < n_bins:
                bins[idx] += 1
        starts = [first_bin_start + i * bin_w for i in range(n_bins)]
        peak = max(bins) if bins else 0
        return {
            "control_out": None,
            "bins": bins,
            "bin_starts_s": starts,
            "total": int(sum(bins)),
            "peak_bin": int(peak),
        }


# ---------------------------------------------------------------------------
# traffic.report.percentile_bundle — common spread metrics
# ---------------------------------------------------------------------------


PCT_SPEC = NodeSpec(
    type="traffic.report.percentile_bundle",
    version="1.0.0",
    display_name="Report · Percentile Bundle",
    category="Traffic Report",
    summary="Mean, stdev, p15, p50, p85, p95 over a numeric list.",
    description="Stateless percentile summary used by reporting widgets.",
    icon="bar-chart-2",
    tags=["traffic", "report", "stats"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="values", type=t_list(t_float()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="mean", type=t_float()),
        PortSpec(name="stdev", type=t_float()),
        PortSpec(name="p15", type=t_float()),
        PortSpec(name="p50", type=t_float()),
        PortSpec(name="p85", type=t_float()),
        PortSpec(name="p95", type=t_float()),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="auto",
)


def _percentile(sorted_vals: List[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    idx = (len(sorted_vals) - 1) * p
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = idx - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


@register_node(PCT_SPEC)
class ReportPercentileNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("values") or []
        vals = sorted(float(v) for v in raw if v is not None)
        n = len(vals)
        if n == 0:
            return {
                "control_out": None, "mean": 0.0, "stdev": 0.0,
                "p15": 0.0, "p50": 0.0, "p85": 0.0, "p95": 0.0, "n": 0,
            }
        return {
            "control_out": None,
            "mean": float(statistics.fmean(vals)),
            "stdev": float(statistics.pstdev(vals)) if n > 1 else 0.0,
            "p15": _percentile(vals, 0.15),
            "p50": _percentile(vals, 0.50),
            "p85": _percentile(vals, 0.85),
            "p95": _percentile(vals, 0.95),
            "n": n,
        }


# ---------------------------------------------------------------------------
# traffic.report.travel_time_indices — TTI, PTI, BI
# ---------------------------------------------------------------------------


TTI_SPEC = NodeSpec(
    type="traffic.report.travel_time_indices",
    version="1.0.0",
    display_name="Report · Travel-time Reliability",
    category="Traffic Report",
    summary="TTI, PTI, BI over a list of observed travel times.",
    description=(
        "TTI = mean / free-flow; PTI = p95 / free-flow; BI = (p95 - mean) / "
        "mean. FHWA's 'Travel Time Reliability' framework defines each."
    ),
    icon="trending-up",
    tags=["traffic", "report", "reliability"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="travel_times_s", type=t_list(t_float()), required=True),
        PortSpec(name="free_flow_s", type=t_float(), required=True,
                 constraints={"min": 1e-6}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="travel_time_index", type=t_float()),
        PortSpec(name="planning_time_index", type=t_float()),
        PortSpec(name="buffer_index", type=t_float()),
        PortSpec(name="mean_s", type=t_float()),
        PortSpec(name="p95_s", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(TTI_SPEC)
class ReportTravelTimeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("travel_times_s") or []
        ff = float(inputs.get("free_flow_s") or 1.0)
        if ff <= 0:
            raise NodeInputError("free_flow_s must be > 0", port="free_flow_s")
        vals = sorted(float(v) for v in raw if v is not None and float(v) > 0)
        if not vals:
            return {
                "control_out": None,
                "travel_time_index": 0.0,
                "planning_time_index": 0.0,
                "buffer_index": 0.0,
                "mean_s": 0.0,
                "p95_s": 0.0,
            }
        mean = statistics.fmean(vals)
        p95 = _percentile(vals, 0.95)
        return {
            "control_out": None,
            "travel_time_index": float(mean / ff),
            "planning_time_index": float(p95 / ff),
            "buffer_index": float((p95 - mean) / mean) if mean > 0 else 0.0,
            "mean_s": float(mean),
            "p95_s": float(p95),
        }


# ---------------------------------------------------------------------------
# traffic.report.snapshot_writer — dump JSON to disk
# ---------------------------------------------------------------------------


SNAP_SPEC = NodeSpec(
    type="traffic.report.snapshot_writer",
    version="1.0.0",
    display_name="Report · Snapshot Writer (JSON)",
    category="Traffic Report",
    summary="Write a payload to disk as a one-line JSON file.",
    description=(
        "Side-effecting writer for daily / periodic reports. Creates the "
        "parent directory if missing. Returns the absolute path written."
    ),
    icon="save",
    tags=["traffic", "report", "io"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="payload", type=t_any(), required=True),
        PortSpec(name="path", type=t_string(), required=True,
                 description="Absolute or relative path to write"),
        PortSpec(name="pretty", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="path", type=t_string()),
        PortSpec(name="bytes_written", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SNAP_SPEC)
class ReportSnapshotNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        path = str(inputs.get("path") or "")
        if not path:
            raise NodeInputError("path required", port="path")
        payload = inputs.get("payload")
        pretty = bool(inputs.get("pretty") or False)
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
            blob = json.dumps(
                payload,
                indent=2 if pretty else None,
                default=str,
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(blob)
            n = len(blob.encode("utf-8"))
        except OSError as e:
            raise NodeRuntimeError(
                f"failed to write snapshot: {e}",
                details={"path": path},
            ) from e
        ctx.log(f"Wrote snapshot {path} ({n} bytes)")
        return {"control_out": None, "path": os.path.abspath(path),
                "bytes_written": int(n)}


# ---------------------------------------------------------------------------
# traffic.report.event_summary — counts per kind / severity
# ---------------------------------------------------------------------------


EVT_SUMMARY_SPEC = NodeSpec(
    type="traffic.report.event_summary",
    version="1.0.0",
    display_name="Report · Event Summary",
    category="Traffic Report",
    summary="Tally a list of TrafficEvents by kind and severity.",
    description="Stateless. Output is suitable for direct dashboard binding.",
    icon="list",
    tags=["traffic", "report", "events"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="by_kind", type=t_map(t_string(), t_int())),
        PortSpec(name="by_severity", type=t_map(t_string(), t_int())),
        PortSpec(name="total", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(EVT_SUMMARY_SPEC)
class ReportEventSummaryNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        evs = [e for e in (inputs.get("events") or []) if is_event(e)]
        by_kind: Dict[str, int] = {}
        by_sev: Dict[str, int] = {}
        for e in evs:
            k = str(e.get("kind") or "unknown")
            s = str(e.get("severity") or "info")
            by_kind[k] = by_kind.get(k, 0) + 1
            by_sev[s] = by_sev.get(s, 0) + 1
        return {
            "control_out": None,
            "by_kind": by_kind,
            "by_severity": by_sev,
            "total": len(evs),
        }


# ---------------------------------------------------------------------------
# traffic.report.csv_emit — render a list-of-records as CSV text
# ---------------------------------------------------------------------------


CSV_SPEC = NodeSpec(
    type="traffic.report.csv_emit",
    version="1.0.0",
    display_name="Report · CSV Emit",
    category="Traffic Report",
    summary="Emit a list of dicts as a CSV-formatted string.",
    description=(
        "Header row is the union of all keys present in the records, "
        "ordered alphabetically. Useful for downstream snapshot writers "
        "or display widgets."
    ),
    icon="file-text",
    tags=["traffic", "report", "csv"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="records", type=t_list(t_any()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="csv", type=t_string()),
        PortSpec(name="rows", type=t_int()),
        PortSpec(name="cols", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(CSV_SPEC)
class ReportCSVNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        rec_in = inputs.get("records") or []
        records = [r for r in rec_in if isinstance(r, dict)]
        keys: List[str] = sorted({k for r in records for k in r.keys()})
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=keys)
        writer.writeheader()
        for r in records:
            writer.writerow({k: r.get(k, "") for k in keys})
        return {
            "control_out": None,
            "csv": buf.getvalue(),
            "rows": len(records),
            "cols": len(keys),
        }
