"""Traffic flow nodes — AADT, density, capacity, time/space-mean speed."""

from __future__ import annotations

from typing import Any, Dict, List

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
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

from .types import t_traffic_event


# ---------------------------------------------------------------------------
# traffic.flow.aadt_estimate — extrapolate AADT from a short count
# ---------------------------------------------------------------------------


AADT_SPEC = NodeSpec(
    type="traffic.flow.aadt_estimate",
    version="1.0.0",
    display_name="Flow · AADT Estimate",
    category="Traffic Flow",
    summary="Estimate Annual Average Daily Traffic from a short count.",
    description=(
        "Annual Average Daily Traffic = short_period_count * adjustment / "
        "duration_hours / 24. Adjustment factors (axle, seasonal, day-of-"
        "week) default to 1.0 — pass real factors for production use."
    ),
    icon="trending-up",
    tags=["traffic", "flow", "aadt"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="count", type=t_int(), required=True,
                 description="Vehicle count over the observation window",
                 constraints={"min": 0}),
        PortSpec(name="duration_hours", type=t_float(), required=False,
                 default=1.0, description="Length of the observation window (h)",
                 constraints={"min": 1e-6}),
        PortSpec(name="seasonal_factor", type=t_float(), required=False,
                 default=1.0, constraints={"min": 0.0}),
        PortSpec(name="dow_factor", type=t_float(), required=False, default=1.0,
                 description="Day-of-week adjustment factor",
                 constraints={"min": 0.0}),
        PortSpec(name="axle_factor", type=t_float(), required=False, default=1.0,
                 description="Axle-correction factor (use 1.0 for camera counts)",
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="aadt", type=t_float()),
        PortSpec(name="hourly_rate", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(AADT_SPEC)
class FlowAadtNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        cnt = int(inputs.get("count") or 0)
        dur_h = float(inputs.get("duration_hours") or 1.0)
        season = float(inputs.get("seasonal_factor") or 1.0)
        dow = float(inputs.get("dow_factor") or 1.0)
        axle = float(inputs.get("axle_factor") or 1.0)
        if dur_h <= 0:
            raise NodeInputError("duration_hours must be > 0", port="duration_hours")
        hourly = cnt / dur_h
        aadt = hourly * 24.0 * season * dow * axle
        return {"control_out": None, "aadt": aadt, "hourly_rate": hourly}


# ---------------------------------------------------------------------------
# traffic.flow.peak_hour_factor
# ---------------------------------------------------------------------------


PHF_SPEC = NodeSpec(
    type="traffic.flow.peak_hour_factor",
    version="1.0.0",
    display_name="Flow · Peak Hour Factor",
    category="Traffic Flow",
    summary="PHF = hourly_volume / (4 * peak_15min_volume).",
    description=(
        "Highway Capacity Manual definition. Inputs are four 15-minute "
        "counts that sum to the analysed hour."
    ),
    icon="activity",
    tags=["traffic", "flow", "phf"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="counts_15min", type=t_list(t_int()), required=True,
                 description="Four 15-minute volume counts"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="phf", type=t_float()),
        PortSpec(name="hourly_volume", type=t_int()),
        PortSpec(name="peak_15", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(PHF_SPEC)
class FlowPHFNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("counts_15min") or []
        counts = [int(c) for c in raw if c is not None]
        if not counts:
            return {
                "control_out": None,
                "phf": 0.0,
                "hourly_volume": 0,
                "peak_15": 0,
            }
        peak = max(counts)
        total = sum(counts)
        phf = total / (4.0 * peak) if peak > 0 else 0.0
        return {
            "control_out": None,
            "phf": float(phf),
            "hourly_volume": int(total),
            "peak_15": int(peak),
        }


# ---------------------------------------------------------------------------
# traffic.flow.density — k = q / v fundamental relation
# ---------------------------------------------------------------------------


DENSITY_SPEC = NodeSpec(
    type="traffic.flow.density",
    version="1.0.0",
    display_name="Flow · Density (k = q/v)",
    category="Traffic Flow",
    summary="Density (veh/km/lane) from flow (veh/h) and space-mean speed (km/h).",
    description=(
        "Fundamental relation k = q / v. Speed must be the *space-mean* "
        "speed for the relation to be exact (Edie's definition). When "
        "the upstream speed estimator hasn't accumulated samples yet "
        "(``v == 0``) this node emits density 0 rather than erroring "
        "— useful for live pipelines that bind to the same dashboard."
    ),
    icon="layers",
    tags=["traffic", "flow", "density"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="flow_vph", type=t_float(), required=True,
                 description="Flow in vehicles per hour", constraints={"min": 0.0}),
        PortSpec(name="space_mean_speed_kph", type=t_float(), required=True,
                 description="Space-mean speed (km/h)",
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="density_vpkm", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(DENSITY_SPEC)
class FlowDensityNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        q = float(inputs.get("flow_vph") or 0.0)
        v = float(inputs.get("space_mean_speed_kph") or 0.0)
        if v < 1e-6:
            return {"control_out": None, "density_vpkm": 0.0}
        return {"control_out": None, "density_vpkm": q / v}


# ---------------------------------------------------------------------------
# traffic.flow.capacity_vc — HCM v/c ratio
# ---------------------------------------------------------------------------


VC_SPEC = NodeSpec(
    type="traffic.flow.capacity_vc",
    version="1.0.0",
    display_name="Flow · v/c Ratio",
    category="Traffic Flow",
    summary="Volume / capacity ratio (HCM).",
    description=(
        "Demand volume divided by lane capacity. v/c >= 1.0 indicates "
        "the segment is operating at or above its design capacity."
    ),
    icon="gauge",
    tags=["traffic", "flow", "hcm"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="volume_vph", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="capacity_vph", type=t_float(), required=False,
                 default=2200.0,
                 description="Lane capacity (HCM default 2200 vph for freeways)",
                 constraints={"min": 1.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="vc", type=t_float()),
        PortSpec(name="status", type=t_string()),
    ],
    cache_policy="auto",
)


@register_node(VC_SPEC)
class FlowVCNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        v = float(inputs.get("volume_vph") or 0.0)
        c = float(inputs.get("capacity_vph") or 1.0)
        vc = v / c if c > 0 else 0.0
        if vc < 0.6:
            status = "uncongested"
        elif vc < 0.85:
            status = "approaching capacity"
        elif vc < 1.0:
            status = "near capacity"
        else:
            status = "over capacity"
        return {"control_out": None, "vc": float(vc), "status": status}


# ---------------------------------------------------------------------------
# traffic.flow.saturation_flow — base saturation rate from green time + volume
# ---------------------------------------------------------------------------


SAT_SPEC = NodeSpec(
    type="traffic.flow.saturation_flow",
    version="1.0.0",
    display_name="Flow · Saturation Flow Rate",
    category="Traffic Flow",
    summary="Estimate saturation flow from observed headways during green.",
    description=(
        "Saturation flow s = 3600 / h_sat where h_sat is the average "
        "headway between vehicles departing on green. HCM default base "
        "rate is 1900 pcphpl."
    ),
    icon="gauge",
    tags=["traffic", "flow"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="headways_s", type=t_list(t_float()), required=True,
                 description="Observed headways during green (seconds)"),
        PortSpec(name="trim_first", type=t_int(), required=False, default=4,
                 description="Drop the first N headways (start-up loss)",
                 constraints={"min": 0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="sat_flow_vph", type=t_float()),
        PortSpec(name="mean_headway_s", type=t_float()),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(SAT_SPEC)
class FlowSaturationNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("headways_s") or []
        trim = int(inputs.get("trim_first") or 4)
        hd = [float(h) for h in raw if h is not None]
        if trim:
            hd = hd[trim:]
        if not hd:
            return {
                "control_out": None,
                "sat_flow_vph": 0.0,
                "mean_headway_s": 0.0,
                "n": 0,
            }
        mean_h = sum(hd) / len(hd)
        sat = 3600.0 / mean_h if mean_h > 1e-9 else 0.0
        return {
            "control_out": None,
            "sat_flow_vph": float(sat),
            "mean_headway_s": float(mean_h),
            "n": len(hd),
        }


# ---------------------------------------------------------------------------
# traffic.flow.fundamental — Greenshields linear v(k) model
# ---------------------------------------------------------------------------


FUNDAMENTAL_SPEC = NodeSpec(
    type="traffic.flow.fundamental_greenshields",
    version="1.0.0",
    display_name="Flow · Fundamental Diagram (Greenshields)",
    category="Traffic Flow",
    summary="Greenshields linear speed-density model.",
    description=(
        "v = vf * (1 - k / kjam). Returns the matched flow q = k*v plus "
        "the model's free-flow speed and jam density used."
    ),
    icon="trending-down",
    tags=["traffic", "flow", "fundamental"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="density_vpkm", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="free_flow_speed_kph", type=t_float(), required=False,
                 default=100.0, constraints={"min": 1.0}),
        PortSpec(name="jam_density_vpkm", type=t_float(), required=False,
                 default=200.0, constraints={"min": 1.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="speed_kph", type=t_float()),
        PortSpec(name="flow_vph", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(FUNDAMENTAL_SPEC)
class FlowFundamentalNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        k = float(inputs.get("density_vpkm") or 0.0)
        vf = float(inputs.get("free_flow_speed_kph") or 100.0)
        kj = float(inputs.get("jam_density_vpkm") or 200.0)
        v = max(0.0, vf * (1.0 - (k / kj if kj > 0 else 0.0)))
        q = k * v
        return {"control_out": None, "speed_kph": float(v), "flow_vph": float(q)}


# ---------------------------------------------------------------------------
# traffic.flow.time_vs_space_mean
# ---------------------------------------------------------------------------


TMS_SMS_SPEC = NodeSpec(
    type="traffic.flow.time_vs_space_mean",
    version="1.0.0",
    display_name="Flow · Time-Mean vs Space-Mean Speed",
    category="Traffic Flow",
    summary="Both means from a list of per-vehicle spot speeds.",
    description=(
        "Time-mean = arithmetic mean of speeds; space-mean = harmonic "
        "mean (= len / sum(1/v)). Space-mean is the correct value for "
        "k = q/v."
    ),
    icon="activity",
    tags=["traffic", "flow", "speed"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="speeds_kph", type=t_list(t_float()), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="time_mean_kph", type=t_float()),
        PortSpec(name="space_mean_kph", type=t_float()),
        PortSpec(name="n", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(TMS_SMS_SPEC)
class FlowTMSSMSNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        raw = inputs.get("speeds_kph") or []
        speeds = [float(v) for v in raw if v is not None and float(v) > 0]
        if not speeds:
            return {
                "control_out": None,
                "time_mean_kph": 0.0,
                "space_mean_kph": 0.0,
                "n": 0,
            }
        tms = sum(speeds) / len(speeds)
        sms = len(speeds) / sum(1.0 / v for v in speeds)
        return {
            "control_out": None,
            "time_mean_kph": float(tms),
            "space_mean_kph": float(sms),
            "n": len(speeds),
        }


# ---------------------------------------------------------------------------
# traffic.flow.live_metrics — running flow metrics from a live counter
# ---------------------------------------------------------------------------
#
# Wires directly to ``traffic.count.line.total`` (or any counter int) +
# a clock source, and extrapolates AADT / hourly / per-minute rate from
# elapsed wall-clock time. Stateful: records the timestamp of the first
# non-zero count it sees so the elapsed window is grounded in observed
# data, not the run boot time.

import time as _time  # noqa: E402  (placed near use to keep top imports lean)


LIVE_METRICS_SPEC = NodeSpec(
    type="traffic.flow.live_metrics",
    version="1.0.0",
    display_name="Flow · Live Metrics",
    category="Traffic Flow",
    summary="Convert a running count into AADT / hourly / per-minute rates.",
    description=(
        "Extrapolates a short-window observed count to longer horizons:\n\n"
        "* ``per_min`` = count * 60 / elapsed_seconds\n"
        "* ``hourly`` = count * 3600 / elapsed_seconds\n"
        "* ``aadt`` = hourly * 24 * seasonal * dow * axle\n\n"
        "Stateful — keeps the timestamp of the first observation so very "
        "short demo loops still produce meaningful rates rather than div-"
        "by-zero noise. Wire ``count`` from a live counter such as "
        "``traffic.count.line.total`` or ``traffic.count.aggregate.total``."
    ),
    icon="trending-up",
    tags=["traffic", "flow", "live", "aadt"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="count", type=t_int(), required=True,
                 description="Cumulative observed count so far",
                 constraints={"min": 0}),
        PortSpec(name="seasonal_factor", type=t_float(), required=False,
                 default=1.0, constraints={"min": 0.0}),
        PortSpec(name="dow_factor", type=t_float(), required=False,
                 default=1.0, constraints={"min": 0.0}),
        PortSpec(name="axle_factor", type=t_float(), required=False,
                 default=1.0, constraints={"min": 0.0}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="elapsed_s", type=t_float()),
        PortSpec(name="rate_per_min", type=t_float()),
        PortSpec(name="hourly_rate", type=t_float()),
        PortSpec(name="aadt", type=t_float()),
    ],
    cache_policy="disabled",
)


_LIVE_METRICS_KEY = "live_metrics.state"


@register_node(LIVE_METRICS_SPEC)
class FlowLiveMetricsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        cnt = max(0, int(inputs.get("count") or 0))
        season = float(inputs.get("seasonal_factor") or 1.0)
        dow = float(inputs.get("dow_factor") or 1.0)
        axle = float(inputs.get("axle_factor") or 1.0)
        reset = bool(inputs.get("reset") or False)

        bucket = ctx.node_resources.setdefault(self.id, {})
        state = bucket.setdefault(_LIVE_METRICS_KEY, {"started": None})
        if reset:
            state["started"] = None
        if state["started"] is None and cnt > 0:
            state["started"] = _time.time()
        elapsed = (
            max(1e-3, _time.time() - state["started"])
            if state["started"] is not None
            else 0.0
        )
        if elapsed <= 0:
            return {
                "control_out": None,
                "elapsed_s": 0.0,
                "rate_per_min": 0.0,
                "hourly_rate": 0.0,
                "aadt": 0.0,
            }
        per_min = cnt * 60.0 / elapsed
        hourly = cnt * 3600.0 / elapsed
        aadt = hourly * 24.0 * season * dow * axle
        return {
            "control_out": None,
            "elapsed_s": float(elapsed),
            "rate_per_min": float(per_min),
            "hourly_rate": float(hourly),
            "aadt": float(aadt),
        }


# ---------------------------------------------------------------------------
# traffic.flow.live_phf — rolling 15-min Peak-Hour Factor from line crossings
# ---------------------------------------------------------------------------


LIVE_PHF_SPEC = NodeSpec(
    type="traffic.flow.live_phf",
    version="1.0.0",
    display_name="Flow · Live Peak-Hour Factor",
    category="Traffic Flow",
    summary="Bin a live event stream into 15-min windows and emit PHF.",
    description=(
        "Accumulates timestamps from ``events`` (typically wired from "
        "``traffic.count.line.events``) and builds a sliding hour of "
        "four 15-minute bins. Emits the 4-tuple plus the canonical PHF "
        "(hourly_volume / (4 * peak_15)). Useful as an unattended live "
        "version of ``traffic.flow.peak_hour_factor`` that doesn't require "
        "the user to feed pre-binned counts."
    ),
    icon="activity",
    tags=["traffic", "flow", "phf", "live"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="events", type=t_list(t_traffic_event()), required=True,
                 description='Wire from a counter\'s "events" port'),
        PortSpec(name="bin_seconds", type=t_float(), required=False,
                 default=900.0,
                 description="Bin width in seconds (default 15 min)",
                 constraints={"min": 1.0}),
        PortSpec(name="kind_filter", type=t_string(), required=False,
                 default="line_cross",
                 description='Only count events with this "kind" (or "" for all)'),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="phf", type=t_float()),
        PortSpec(name="hourly_volume", type=t_int()),
        PortSpec(name="peak_15", type=t_int()),
        PortSpec(name="bins", type=t_list(t_int()),
                 description="Counts in the 4 most-recent 15-min bins"),
    ],
    cache_policy="disabled",
)


_LIVE_PHF_KEY = "live_phf.times"


# Deferred import to avoid a top-level cycle with the events module.
def _filter_event_times(events_in: List[Any], kind: str) -> List[float]:
    out: List[float] = []
    for e in events_in or []:
        if not isinstance(e, dict):
            continue
        if kind and str(e.get("kind") or "").lower() != kind:
            continue
        ts = e.get("ts_start")
        if ts is None:
            continue
        try:
            out.append(float(ts))
        except (TypeError, ValueError):
            continue
    return out


@register_node(LIVE_PHF_SPEC)
class FlowLivePHFNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        bin_w = float(inputs.get("bin_seconds") or 900.0)
        kind = (inputs.get("kind_filter") or "").strip().lower()
        reset = bool(inputs.get("reset") or False)
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _LIVE_PHF_KEY not in bucket:
            bucket[_LIVE_PHF_KEY] = []
        buf: List[float] = bucket[_LIVE_PHF_KEY]
        buf.extend(_filter_event_times(inputs.get("events") or [], kind))

        if not buf:
            return {
                "control_out": None,
                "phf": 0.0,
                "hourly_volume": 0,
                "peak_15": 0,
                "bins": [0, 0, 0, 0],
            }

        # Drop everything older than 4 bin-widths from the most recent ts.
        latest = max(buf)
        cutoff = latest - 4.0 * bin_w
        bucket[_LIVE_PHF_KEY] = [t for t in buf if t >= cutoff]
        buf = bucket[_LIVE_PHF_KEY]

        bins = [0, 0, 0, 0]
        for t in buf:
            offset = latest - t
            idx = 3 - int(offset // bin_w)  # 3 = newest bin
            if 0 <= idx < 4:
                bins[idx] += 1
        peak = max(bins)
        total = sum(bins)
        phf = total / (4.0 * peak) if peak > 0 else 0.0
        return {
            "control_out": None,
            "phf": float(phf),
            "hourly_volume": int(total),
            "peak_15": int(peak),
            "bins": bins,
        }
