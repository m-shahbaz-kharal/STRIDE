"""
Node specification classes for LiGuard-Web.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .typesystem import TypeDescriptor, t_any


@dataclass
class PortSpec:
    """Specification for an input or output port."""
    
    name: str
    type: TypeDescriptor = field(default_factory=t_any)
    required: bool = True
    default: Any = None
    description: str = ""
    ui: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.to_dict(),
            "required": self.required,
            "default": self.default,
            "description": self.description,
            "ui": self.ui,
        }


@dataclass
class ParamSpec:
    """Specification for a node parameter (shown in UI)."""
    
    name: str
    type: str
    label: Optional[str] = None
    description: Optional[str] = None
    default: Any = None
    options: Optional[List[Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "type": self.type,
        }
        if self.label:
            data["label"] = self.label
        if self.description:
            data["description"] = self.description
        if self.default is not None:
            data["default"] = self.default
        if self.options:
            data["options"] = self.options
        return data


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
    params: Dict[str, ParamSpec] = field(default_factory=dict)
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
            "params_schema": {k: v.to_dict() for k, v in self.params.items()},
            "params_defaults": {k: v.default for k, v in self.params.items() if v.default is not None},
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

