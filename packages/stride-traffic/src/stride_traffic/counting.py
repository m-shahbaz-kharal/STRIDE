"""Vehicle counting nodes.

Implements the canonical counter primitives used by traffic-engineering
practice:

* ``traffic.count.line`` — directed line-crossing counter. A track that
  moves from the left of ``(a -> b)`` to the right counts as ``forward``;
  the reverse counts as ``backward``. Stateful: maintains last-known side
  per track id across frames.
* ``traffic.count.polygon`` — enter/exit counter for an arbitrary
  polygon ROI.
* ``traffic.count.classify`` — per-class FHWA-style counter that tallies
  detections by class name.
* ``traffic.count.aggregate`` — running totals over time.

All counters are detector-agnostic: they accept the canonical
``detections2d`` record (preferred — boxes carry ``track_id``) or a
plain ``list<bbox2d>``.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional

# Per-node per-track history cap. ByteTrack assigns monotonically
# increasing IDs in a live deployment, so unbounded per-track state
# would grow without bound after a few hours of operation. 4096 covers
# ~1 hour of dense intersection traffic while staying cheap (<1 MB).
_MAX_TRACK_HISTORY = 4096


def _cap_track_dict(d: "OrderedDict[int, Any]") -> None:
    """FIFO-evict the oldest entries until ``d`` is under the cap."""
    while len(d) > _MAX_TRACK_HISTORY:
        d.popitem(last=False)

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_boolean,
    t_control,
    t_detections2d,
    t_float,
    t_int,
    t_list,
    t_map,
    t_string,
)

from .roi import (
    detection_bottom_center,
    detection_center,
    line_side,
    point_in_polygon,
)
from .types import (
    is_line,
    is_polygon,
    make_event,
    t_traffic_event,
    t_traffic_line,
    t_traffic_polygon,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_boxes(value: Any) -> List[Dict[str, Any]]:
    """Pull a list of box-records out of either a t_detections2d or list."""
    if value is None:
        return []
    if isinstance(value, list):
        return [b for b in value if isinstance(b, dict)]
    if isinstance(value, dict) and "boxes" in value:
        boxes = value.get("boxes") or []
        return [b for b in boxes if isinstance(b, dict)]
    return []


# ---------------------------------------------------------------------------
# traffic.count.line
# ---------------------------------------------------------------------------


LINE_COUNT_SPEC = NodeSpec(
    type="traffic.count.line",
    version="1.0.0",
    display_name="Count · Line Crossing",
    category="Traffic Counting",
    summary="Directed line-crossing counter (per-track, hysteresis).",
    description=(
        "Tallies forward/backward crossings of a virtual line. A track is "
        "counted at most once per crossing per direction (hysteresis "
        "based on perpendicular distance). State is per-run, per-node — "
        "two separate counters never share IDs."
    ),
    icon="minus",
    tags=["traffic", "count", "line"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True,
                 description="Tracked detections (ByteTrack or similar)"),
        PortSpec(name="line", type=t_traffic_line(), required=True,
                 description="Virtual counting line"),
        PortSpec(name="reference", type=t_string(), required=False,
                 default="bottom",
                 description="Anchor: 'center' or 'bottom'",
                 constraints={"enum": ["center", "bottom"]}),
        PortSpec(name="hysteresis_px", type=t_float(), required=False,
                 default=2.0,
                 description="Min perpendicular pixel distance to register a side change",
                 constraints={"min": 0.0}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="forward", type=t_int()),
        PortSpec(name="backward", type=t_int()),
        PortSpec(name="total", type=t_int()),
        PortSpec(name="events", type=t_list(t_traffic_event()),
                 description="One event per fresh crossing this frame"),
    ],
    cache_policy="disabled",
)


_LINE_STATE_KEY = "line_counter.state"


@register_node(LINE_COUNT_SPEC)
class CountLineNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        line = inputs.get("line")
        if not is_line(line):
            raise NodeInputError("line must be a TrafficLine record", port="line")
        boxes = _extract_boxes(inputs.get("detections"))
        ref = str(inputs.get("reference") or "bottom")
        hyst = float(inputs.get("hysteresis_px") or 0.0)
        reset = bool(inputs.get("reset") or False)

        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _LINE_STATE_KEY not in bucket:
            from collections import OrderedDict
            bucket[_LINE_STATE_KEY] = {
                # FIFO-capped via _cap_track_dict — see counting module
                # docstring on long-running deployments.
                "last_side": OrderedDict(),   # track_id -> +1/-1/0
                "forward": 0,
                "backward": 0,
                "counted": set(),  # track_id -> set of crossing directions seen
            }
        state = bucket[_LINE_STATE_KEY]
        if not isinstance(state["last_side"], dict) or type(state["last_side"]).__name__ != "OrderedDict":
            # Promote any pre-cap state dict.
            from collections import OrderedDict
            state["last_side"] = OrderedDict(state["last_side"])

        events: List[Dict[str, Any]] = []
        anchor = (
            detection_bottom_center if ref == "bottom" else detection_center
        )

        for det in boxes:
            tid = det.get("track_id") if det.get("track_id") is not None else det.get("id")
            if tid is None:
                continue
            tid = int(tid)
            pt = anchor(det)
            if pt is None:
                continue
            d = line_side(line, pt)
            if abs(d) < hyst:
                continue  # inside dead zone — don't update side
            side = 1 if d > 0 else -1
            prev = state["last_side"].get(tid)
            # Refresh-insert so the just-touched track moves to the end
            # of the FIFO; cap to _MAX_TRACK_HISTORY entries.
            state["last_side"].pop(tid, None)
            state["last_side"][tid] = side
            _cap_track_dict(state["last_side"])
            if prev is None or prev == 0 or prev == side:
                continue
            # Side flipped — register a crossing.
            # Convention: positive line_side = LEFT of (a -> b), negative = RIGHT.
            # "Forward" is left-to-right (positive -> negative).
            ts = time.time()
            if prev == 1 and side == -1:
                state["forward"] += 1
                events.append(make_event(
                    kind="line_cross", severity="info",
                    track_ids=[tid], ts_start=ts,
                    metric=float(d),
                    label=f"forward across '{line.get('name')}'",
                    details={
                        "direction": "forward",
                        "line": line.get("name"),
                        "class_name": det.get("class_name"),
                    },
                ))
            elif prev == -1 and side == 1:
                state["backward"] += 1
                events.append(make_event(
                    kind="line_cross", severity="info",
                    track_ids=[tid], ts_start=ts,
                    metric=float(d),
                    label=f"backward across '{line.get('name')}'",
                    details={
                        "direction": "backward",
                        "line": line.get("name"),
                        "class_name": det.get("class_name"),
                    },
                ))

        return {
            "control_out": None,
            "forward": int(state["forward"]),
            "backward": int(state["backward"]),
            "total": int(state["forward"] + state["backward"]),
            "events": events,
        }


# ---------------------------------------------------------------------------
# traffic.count.polygon — enter/exit counter
# ---------------------------------------------------------------------------


POLY_COUNT_SPEC = NodeSpec(
    type="traffic.count.polygon",
    version="1.0.0",
    display_name="Count · Polygon Enter/Exit",
    category="Traffic Counting",
    summary="Per-track enter/exit counts for a polygon ROI.",
    description=(
        "Tracks transitions of a track's anchor point across a polygon "
        "boundary. Each track contributes at most one enter and one exit "
        "event per traversal."
    ),
    icon="hexagon",
    tags=["traffic", "count"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="polygon", type=t_traffic_polygon(), required=True),
        PortSpec(name="reference", type=t_string(), required=False, default="bottom",
                 constraints={"enum": ["center", "bottom"]}),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="entered", type=t_int()),
        PortSpec(name="exited", type=t_int()),
        PortSpec(name="inside", type=t_int(), description="Tracks currently inside"),
        PortSpec(name="events", type=t_list(t_traffic_event())),
    ],
    cache_policy="disabled",
)


_POLY_STATE_KEY = "poly_counter.state"


@register_node(POLY_COUNT_SPEC)
class CountPolygonNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        poly = inputs.get("polygon")
        if not is_polygon(poly):
            raise NodeInputError("polygon must be a TrafficPolygon", port="polygon")
        boxes = _extract_boxes(inputs.get("detections"))
        ref = str(inputs.get("reference") or "bottom")
        reset = bool(inputs.get("reset") or False)

        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _POLY_STATE_KEY not in bucket:
            bucket[_POLY_STATE_KEY] = {
                # Ordered so we can FIFO-evict — see ``_cap_track_dict``.
                "inside": OrderedDict(),
                "entered": 0,
                "exited": 0,
            }
        state = bucket[_POLY_STATE_KEY]
        if isinstance(state["inside"], set):
            state["inside"] = OrderedDict((tid, True) for tid in state["inside"])
        anchor = (
            detection_bottom_center if ref == "bottom" else detection_center
        )

        seen_inside: set = set()
        events: List[Dict[str, Any]] = []
        for det in boxes:
            tid = det.get("track_id") if det.get("track_id") is not None else det.get("id")
            if tid is None:
                continue
            tid = int(tid)
            pt = anchor(det)
            if pt is None:
                continue
            inside = point_in_polygon(pt, poly)
            was_inside = tid in state["inside"]
            if inside:
                seen_inside.add(tid)
                if not was_inside:
                    state["entered"] += 1
                    state["inside"][tid] = True
                    _cap_track_dict(state["inside"])
                    events.append(make_event(
                        kind="line_cross", severity="info",
                        track_ids=[tid], ts_start=time.time(),
                        label=f"entered '{poly.get('name')}'",
                        details={
                            "direction": "enter",
                            "polygon": poly.get("name"),
                            "class_name": det.get("class_name"),
                        },
                    ))
            else:
                if was_inside:
                    state["exited"] += 1
                    state["inside"].pop(tid, None)
                    events.append(make_event(
                        kind="line_cross", severity="info",
                        track_ids=[tid], ts_start=time.time(),
                        label=f"exited '{poly.get('name')}'",
                        details={
                            "direction": "exit",
                            "polygon": poly.get("name"),
                            "class_name": det.get("class_name"),
                        },
                    ))
        # Tracks no longer detected don't auto-exit (they may just be occluded)

        return {
            "control_out": None,
            "entered": int(state["entered"]),
            "exited": int(state["exited"]),
            "inside": len(state["inside"]),
            "events": events,
        }


# ---------------------------------------------------------------------------
# traffic.count.classify — running tallies per class
# ---------------------------------------------------------------------------


CLASSIFY_SPEC = NodeSpec(
    type="traffic.count.classify",
    version="1.0.0",
    display_name="Count · Classification (FHWA scheme F)",
    category="Traffic Counting",
    summary="Running per-class tallies (motorcycle / car / bus / truck / …).",
    description=(
        "Counts unique track IDs per class. Defaults align with FHWA "
        "classification scheme F bins (motorcycle, passenger, light truck, "
        "bus, single-unit truck, semi, multi-trailer)."
    ),
    icon="bar-chart",
    tags=["traffic", "count", "classification"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="detections", type=t_detections2d(), required=True),
        PortSpec(name="map_motorcycle", type=t_string(), required=False,
                 default="motorcycle"),
        PortSpec(name="map_car", type=t_string(), required=False,
                 default="car"),
        PortSpec(name="map_bus", type=t_string(), required=False,
                 default="bus"),
        PortSpec(name="map_truck", type=t_string(), required=False,
                 default="truck"),
        PortSpec(name="map_bicycle", type=t_string(), required=False,
                 default="bicycle"),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="counts", type=t_map(t_string(), t_int())),
        PortSpec(name="total", type=t_int()),
        PortSpec(name="summary", type=t_string()),
    ],
    cache_policy="disabled",
)


_CLASS_STATE_KEY = "class_counter.state"

_FHWA_BINS = ("motorcycle", "car", "bus", "truck", "bicycle", "other")


@register_node(CLASSIFY_SPEC)
class CountClassifyNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        boxes = _extract_boxes(inputs.get("detections"))
        reset = bool(inputs.get("reset") or False)

        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _CLASS_STATE_KEY not in bucket:
            bucket[_CLASS_STATE_KEY] = {
                # FIFO-capped ordered "set" so 24/7 deployments don't
                # accumulate every track ID ever seen forever.
                "seen": OrderedDict(),
                "counts": {b: 0 for b in _FHWA_BINS},
            }
        state = bucket[_CLASS_STATE_KEY]
        if isinstance(state["seen"], set):
            state["seen"] = OrderedDict((tid, True) for tid in state["seen"])
        mapping = {
            (inputs.get("map_motorcycle") or "motorcycle").lower(): "motorcycle",
            (inputs.get("map_car") or "car").lower(): "car",
            (inputs.get("map_bus") or "bus").lower(): "bus",
            (inputs.get("map_truck") or "truck").lower(): "truck",
            (inputs.get("map_bicycle") or "bicycle").lower(): "bicycle",
        }

        for det in boxes:
            tid = det.get("track_id") if det.get("track_id") is not None else det.get("id")
            if tid is None:
                continue
            tid = int(tid)
            if tid in state["seen"]:
                # Move to end so this id is the freshest, not the oldest.
                state["seen"].move_to_end(tid)
                continue
            state["seen"][tid] = True
            _cap_track_dict(state["seen"])
            cls_raw = str(det.get("class_name") or "").lower()
            bin_name = mapping.get(cls_raw, "other")
            state["counts"][bin_name] = state["counts"].get(bin_name, 0) + 1

        total = sum(state["counts"].values())
        summary = ", ".join(f"{k}={v}" for k, v in state["counts"].items() if v)
        return {
            "control_out": None,
            "counts": dict(state["counts"]),
            "total": int(total),
            "summary": summary or "no detections",
        }


# ---------------------------------------------------------------------------
# traffic.count.aggregate — running totals over time
# ---------------------------------------------------------------------------


AGG_SPEC = NodeSpec(
    type="traffic.count.aggregate",
    version="1.0.0",
    display_name="Count · Aggregate",
    category="Traffic Counting",
    summary="Add a value to a running counter and read total / rate.",
    description=(
        "Increments a per-run accumulator, returning the running total "
        "and an instantaneous rate (counts per second since first call)."
    ),
    icon="plus-circle",
    tags=["traffic", "count"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="value", type=t_int(), required=False, default=1),
        PortSpec(name="reset", type=t_boolean(), required=False, default=False),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="total", type=t_int()),
        PortSpec(name="rate_per_sec", type=t_float()),
        PortSpec(name="seconds", type=t_float()),
    ],
    cache_policy="disabled",
)


_AGG_KEY = "aggregate.state"


@register_node(AGG_SPEC)
class CountAggregateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        reset = bool(inputs.get("reset") or False)
        bucket = ctx.node_resources.setdefault(self.id, {})
        if reset or _AGG_KEY not in bucket:
            bucket[_AGG_KEY] = {"total": 0, "started": time.time()}
        state = bucket[_AGG_KEY]
        try:
            v = int(inputs.get("value") if inputs.get("value") is not None else 1)
        except (TypeError, ValueError):
            v = 1
        state["total"] += v
        elapsed = max(1e-6, time.time() - state["started"])
        return {
            "control_out": None,
            "total": int(state["total"]),
            "rate_per_sec": float(state["total"]) / elapsed,
            "seconds": elapsed,
        }
