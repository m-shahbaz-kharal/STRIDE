"""
Node specification classes for STRIDE.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .typesystem import TypeDescriptor, t_any


@dataclass
class PortSpec:
    """Specification for an input or output port.

    Phase 2 adds the optional ``constraints`` field — a declarative
    vocabulary that ``NodeBase.validate_inputs`` enforces server-side and
    that the frontend will eventually consume to render bounded widgets
    (sliders, enums, file pickers).

    Constraint vocabulary (see §5.3 of the design doc):

    * ``{"min": float, "max": float}`` — numeric range.
    * ``{"enum": [v1, v2, ...]}`` — value must be one of the choices.
    * ``{"pattern": "regex"}`` — string must match the regex.
    * ``{"length_min": int, "length_max": int}`` — string / list length.
    * ``{"extensions": ["jpg", "png"]}`` — file-path extension whitelist.
    * ``{"presets": [{"label": "...", "value": ...}]}`` — UI-only hint.

    All keys are optional and may be combined. ``None`` (the default) means
    no declarative constraints — the node enforces its own checks via
    ``validate_inputs``.
    """

    name: str
    type: TypeDescriptor = field(default_factory=t_any)
    required: bool = True
    default: Any = None
    description: str = ""
    ui: Dict[str, Any] = field(default_factory=dict)
    constraints: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "name": self.name,
            "type": self.type.to_dict(),
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "ui": self.ui,
        }
        if self.constraints:
            d["constraints"] = dict(self.constraints)
        return d


@dataclass
class NodeSpec:
    """Complete specification for a node type."""

    type: str
    version: str = "1.0.0"
    display_name: str = ""
    category: str = "General"
    summary: str = ""
    description: str = ""
    icon: str = ""
    tags: List[str] = field(default_factory=list)
    inputs: List[PortSpec] = field(default_factory=list)
    outputs: List[PortSpec] = field(default_factory=list)
    stability: str = "stable"
    cache_policy: str = "auto"

    # Plugin metadata
    plugin_name: Optional[str] = None
    api_version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.type,
            "type": self.type,  # Keep for backwards compatibility
            "version": self.version,
            "display_name": self.display_name or self.type,
            "category": self.category,
            "summary": self.summary or self.description,
            "description": self.description,
            "icon": self.icon,
            "tags": self.tags,
            "inputs": [p.to_dict() for p in self.inputs],
            "outputs": [p.to_dict() for p in self.outputs],
            "stability": self.stability,
            "cache_policy": self.cache_policy,
            "plugin_name": self.plugin_name,
            "api_version": self.api_version,
            # Legacy/compat fields for the current frontend
            "input_ports": [p.name for p in self.inputs],
            "output_ports": [p.name for p in self.outputs],
            "input_port_types": {p.name: p.type.to_dict() for p in self.inputs},
            "output_port_types": {p.name: p.type.to_dict() for p in self.outputs},
        }
