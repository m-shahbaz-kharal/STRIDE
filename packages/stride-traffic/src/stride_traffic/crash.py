"""Crash-prediction nodes — Highway Safety Manual (HSM) machinery.

This module implements the HSM Part C predictive method primitives:

* Safety Performance Functions (SPFs) for rural two-lane segments,
  rural multilane segments, and urban arterials.
* Empirical-Bayes adjustment combining the SPF prediction with
  observed crash counts.
* Crash Modification Factor (CMF) application.
* Crash rate calculator (per million vehicle-miles, per million
  entering vehicles).
* Network-screening helpers (excess-crash and PSI score).
* KABCO -> EPDO cost translation.

The SPF coefficients used here are the published HSM defaults; users
can override every coefficient on the node's input ports for local
calibration.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import NodeInputError
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any,
    t_control,
    t_float,
    t_int,
    t_list,
    t_map,
    t_string,
)


# ---------------------------------------------------------------------------
# traffic.crash.spf_rural_two_lane
# ---------------------------------------------------------------------------


SPF2L_SPEC = NodeSpec(
    type="traffic.crash.spf_rural_two_lane",
    version="1.0.0",
    display_name="Crash · SPF Rural Two-Lane",
    category="Traffic Crash",
    summary="HSM Eq. 10-6 SPF for rural two-lane two-way segments.",
    description=(
        "N_spf = AADT * L * 365 * 1e-6 * exp(-0.312). Returns predicted "
        "crashes per year. Apply CMFs and the calibration factor C "
        "downstream to get the predicted crash frequency."
    ),
    icon="alert-triangle",
    tags=["traffic", "crash", "hsm", "spf"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="aadt", type=t_float(), required=True,
                 description="Annual Average Daily Traffic",
                 constraints={"min": 0.0}),
        PortSpec(name="length_mi", type=t_float(), required=True,
                 description="Segment length (miles)",
                 constraints={"min": 0.0}),
        PortSpec(name="intercept", type=t_float(), required=False,
                 default=-0.312,
                 description="HSM Eq. 10-6 intercept (defaults are total crashes)"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="n_spf_per_year", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(SPF2L_SPEC)
class CrashSpfRural2LNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        aadt = float(inputs.get("aadt") or 0.0)
        L = float(inputs.get("length_mi") or 0.0)
        a = float(inputs.get("intercept") or -0.312)
        n = aadt * L * 365.0 * 1e-6 * math.exp(a)
        return {"control_out": None, "n_spf_per_year": float(n)}


# ---------------------------------------------------------------------------
# traffic.crash.spf_urban_arterial — HSM Ch. 12 base segment SPF
# ---------------------------------------------------------------------------


SPF_URBAN_SPEC = NodeSpec(
    type="traffic.crash.spf_urban_arterial",
    version="1.0.0",
    display_name="Crash · SPF Urban Arterial",
    category="Traffic Crash",
    summary="HSM Ch. 12 SPF for urban / suburban arterial segments.",
    description=(
        "N = exp(a + b * ln(AADT) + ln(L)). Defaults are HSM 4U "
        "(four-lane undivided) total-crash coefficients."
    ),
    icon="alert-triangle",
    tags=["traffic", "crash", "hsm", "spf"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="aadt", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="length_mi", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="a", type=t_float(), required=False, default=-7.99,
                 description="Intercept (HSM 4U default = -7.99)"),
        PortSpec(name="b", type=t_float(), required=False, default=1.17,
                 description="ln(AADT) coefficient (HSM 4U default = 1.17)"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="n_spf_per_year", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(SPF_URBAN_SPEC)
class CrashSpfUrbanNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        aadt = max(1.0, float(inputs.get("aadt") or 0.0))
        L = max(1e-6, float(inputs.get("length_mi") or 0.0))
        a = float(inputs.get("a") or -7.99)
        b = float(inputs.get("b") or 1.17)
        n = math.exp(a + b * math.log(aadt) + math.log(L))
        return {"control_out": None, "n_spf_per_year": float(n)}


# ---------------------------------------------------------------------------
# traffic.crash.spf_intersection — HSM Ch. 12 base intersection SPF
# ---------------------------------------------------------------------------


SPF_INT_SPEC = NodeSpec(
    type="traffic.crash.spf_intersection",
    version="1.0.0",
    display_name="Crash · SPF Intersection",
    category="Traffic Crash",
    summary="HSM Ch. 12 SPF for signalised intersections (4SG).",
    description=(
        "N = exp(a + b * ln(AADT_major) + c * ln(AADT_minor)). Defaults "
        "are 4-leg signalised total-crash coefficients."
    ),
    icon="alert-triangle",
    tags=["traffic", "crash", "hsm", "spf", "intersection"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="aadt_major", type=t_float(), required=True,
                 constraints={"min": 1.0}),
        PortSpec(name="aadt_minor", type=t_float(), required=True,
                 constraints={"min": 1.0}),
        PortSpec(name="a", type=t_float(), required=False, default=-10.99),
        PortSpec(name="b", type=t_float(), required=False, default=1.07),
        PortSpec(name="c", type=t_float(), required=False, default=0.23),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="n_spf_per_year", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(SPF_INT_SPEC)
class CrashSpfIntersectionNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        major = max(1.0, float(inputs.get("aadt_major") or 0.0))
        minor = max(1.0, float(inputs.get("aadt_minor") or 0.0))
        a = float(inputs.get("a") or -10.99)
        b = float(inputs.get("b") or 1.07)
        c = float(inputs.get("c") or 0.23)
        n = math.exp(a + b * math.log(major) + c * math.log(minor))
        return {"control_out": None, "n_spf_per_year": float(n)}


# ---------------------------------------------------------------------------
# traffic.crash.apply_cmfs — multiply N_spf by chained CMFs and calibration
# ---------------------------------------------------------------------------


CMF_SPEC = NodeSpec(
    type="traffic.crash.apply_cmfs",
    version="1.0.0",
    display_name="Crash · Apply CMFs",
    category="Traffic Crash",
    summary="Multiply an SPF prediction by CMFs and calibration factor C.",
    description=(
        "N_predicted = N_spf * Π(CMFi) * C. Crash Modification Factors "
        "are unitless multipliers; values < 1.0 indicate a safety "
        "improvement, > 1.0 indicates a treatment expected to increase "
        "crashes."
    ),
    icon="filter",
    tags=["traffic", "crash", "hsm", "cmf"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="n_spf_per_year", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="cmfs", type=t_list(t_float()), required=False,
                 default=[],
                 description="List of CMFs to apply"),
        PortSpec(name="calibration_factor", type=t_float(), required=False,
                 default=1.0,
                 description="Local calibration factor C (HSM default 1.0)",
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="n_predicted", type=t_float()),
        PortSpec(name="cmf_product", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(CMF_SPEC)
class CrashApplyCMFsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        n_spf = float(inputs.get("n_spf_per_year") or 0.0)
        cmfs = [float(c) for c in (inputs.get("cmfs") or []) if c is not None]
        c = float(inputs.get("calibration_factor") or 1.0)
        prod = 1.0
        for v in cmfs:
            prod *= max(0.0, v)
        n = n_spf * prod * c
        return {
            "control_out": None,
            "n_predicted": float(n),
            "cmf_product": float(prod),
        }


# ---------------------------------------------------------------------------
# traffic.crash.empirical_bayes — combine prediction with observed crashes
# ---------------------------------------------------------------------------


EB_SPEC = NodeSpec(
    type="traffic.crash.empirical_bayes",
    version="1.0.0",
    display_name="Crash · Empirical-Bayes Adjustment",
    category="Traffic Crash",
    summary="Combine N_predicted with N_observed via the EB weight.",
    description=(
        "Weight w = 1 / (1 + k * Σ(N_predicted_i)) where k is the "
        "overdispersion parameter from the SPF, then "
        "N_expected = w * N_predicted_total + (1 - w) * N_observed_total. "
        "Returns N_expected and the EB weight w."
    ),
    icon="trending-down",
    tags=["traffic", "crash", "hsm", "eb"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="n_predicted_total", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="n_observed_total", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="overdispersion_k", type=t_float(), required=False,
                 default=0.236,
                 description="HSM 10.6.1 default = 0.236",
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="n_expected", type=t_float()),
        PortSpec(name="weight", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(EB_SPEC)
class CrashEBNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        n_pred = float(inputs.get("n_predicted_total") or 0.0)
        n_obs = float(inputs.get("n_observed_total") or 0.0)
        k = float(inputs.get("overdispersion_k") or 0.236)
        denom = 1.0 + k * n_pred
        w = 1.0 / denom if denom > 1e-9 else 0.0
        n_exp = w * n_pred + (1.0 - w) * n_obs
        return {
            "control_out": None,
            "n_expected": float(n_exp),
            "weight": float(w),
        }


# ---------------------------------------------------------------------------
# traffic.crash.crash_rate — per MVM / MEV
# ---------------------------------------------------------------------------


RATE_SPEC = NodeSpec(
    type="traffic.crash.crash_rate",
    version="1.0.0",
    display_name="Crash · Rate (per MVM or MEV)",
    category="Traffic Crash",
    summary="Crash rate per million vehicle-miles or entering vehicles.",
    description=(
        "Segment rate = N * 1e6 / (AADT * 365 * length_mi * years). "
        "Intersection rate = N * 1e6 / (AADT_total * 365 * years). "
        "When ``length_mi`` is 0, returns the intersection (MEV) rate. "
        "When ``aadt`` is 0 (e.g. a live counter that hasn't accumulated "
        "any crossings yet) the rate is reported as 0 rather than "
        "erroring — keeps live dashboards happy until data flows."
    ),
    icon="trending-up",
    tags=["traffic", "crash", "rate"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="n_crashes", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="aadt", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="length_mi", type=t_float(), required=False, default=0.0,
                 description="0 -> MEV (intersection); >0 -> MVM (segment)",
                 constraints={"min": 0.0}),
        PortSpec(name="years", type=t_float(), required=False, default=1.0,
                 constraints={"min": 1e-6}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="rate_per_million", type=t_float()),
        PortSpec(name="basis", type=t_string(),
                 description="'MVM' or 'MEV'"),
    ],
    cache_policy="auto",
)


@register_node(RATE_SPEC)
class CrashRateNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        n = float(inputs.get("n_crashes") or 0.0)
        aadt = float(inputs.get("aadt") or 0.0)
        L = float(inputs.get("length_mi") or 0.0)
        yrs = float(inputs.get("years") or 1.0)
        basis = "MVM" if L > 0 else "MEV"
        if aadt < 1e-6:
            return {"control_out": None, "rate_per_million": 0.0, "basis": basis}
        if L > 0:
            denom = aadt * 365.0 * L * yrs
        else:
            denom = aadt * 365.0 * yrs
        rate = (n * 1e6) / max(denom, 1e-9)
        return {
            "control_out": None,
            "rate_per_million": float(rate),
            "basis": basis,
        }


# ---------------------------------------------------------------------------
# traffic.crash.epdo — KABCO -> equivalent property-damage-only weights
# ---------------------------------------------------------------------------


EPDO_SPEC = NodeSpec(
    type="traffic.crash.epdo",
    version="1.0.0",
    display_name="Crash · EPDO from KABCO",
    category="Traffic Crash",
    summary="Compute EPDO crashes from K/A/B/C/O counts.",
    description=(
        "EPDO = w_K*K + w_A*A + w_B*B + w_C*C + w_O*O. Default cost "
        "weights are FHWA Comprehensive Costs (2016, in $1000s): K=11295, "
        "A=655, B=199, C=125, O=10."
    ),
    icon="dollar-sign",
    tags=["traffic", "crash", "kabco"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="k", type=t_int(), required=False, default=0,
                 description="Fatal crashes", constraints={"min": 0}),
        PortSpec(name="a", type=t_int(), required=False, default=0,
                 description="Incapacitating injury", constraints={"min": 0}),
        PortSpec(name="b", type=t_int(), required=False, default=0,
                 description="Non-incapacitating injury", constraints={"min": 0}),
        PortSpec(name="c", type=t_int(), required=False, default=0,
                 description="Possible injury", constraints={"min": 0}),
        PortSpec(name="o", type=t_int(), required=False, default=0,
                 description="Property-damage-only", constraints={"min": 0}),
        PortSpec(name="w_k", type=t_float(), required=False, default=11295.0),
        PortSpec(name="w_a", type=t_float(), required=False, default=655.0),
        PortSpec(name="w_b", type=t_float(), required=False, default=199.0),
        PortSpec(name="w_c", type=t_float(), required=False, default=125.0),
        PortSpec(name="w_o", type=t_float(), required=False, default=10.0),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="epdo", type=t_float()),
        PortSpec(name="total_crashes", type=t_int()),
    ],
    cache_policy="auto",
)


@register_node(EPDO_SPEC)
class CrashEpdoNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        k = int(inputs.get("k") or 0)
        a = int(inputs.get("a") or 0)
        b = int(inputs.get("b") or 0)
        c = int(inputs.get("c") or 0)
        o = int(inputs.get("o") or 0)
        wk = float(inputs.get("w_k") or 11295.0)
        wa = float(inputs.get("w_a") or 655.0)
        wb = float(inputs.get("w_b") or 199.0)
        wc = float(inputs.get("w_c") or 125.0)
        wo = float(inputs.get("w_o") or 10.0)
        epdo = k * wk + a * wa + b * wb + c * wc + o * wo
        return {
            "control_out": None,
            "epdo": float(epdo),
            "total_crashes": int(k + a + b + c + o),
        }


# ---------------------------------------------------------------------------
# traffic.crash.psi — Potential for Safety Improvement (excess crashes)
# ---------------------------------------------------------------------------


PSI_SPEC = NodeSpec(
    type="traffic.crash.psi",
    version="1.0.0",
    display_name="Crash · Potential for Safety Improvement",
    category="Traffic Crash",
    summary="PSI = max(0, N_expected - N_predicted).",
    description=(
        "Network-screening metric: positive PSI indicates a site is "
        "experiencing more crashes than its SPF would suggest, and is "
        "therefore a candidate for further safety investigation."
    ),
    icon="trending-up",
    tags=["traffic", "crash", "psi"],
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="n_expected", type=t_float(), required=True,
                 constraints={"min": 0.0}),
        PortSpec(name="n_predicted", type=t_float(), required=True,
                 constraints={"min": 0.0}),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="psi", type=t_float()),
    ],
    cache_policy="auto",
)


@register_node(PSI_SPEC)
class CrashPSINode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        e = float(inputs.get("n_expected") or 0.0)
        p = float(inputs.get("n_predicted") or 0.0)
        return {"control_out": None, "psi": float(max(0.0, e - p))}
