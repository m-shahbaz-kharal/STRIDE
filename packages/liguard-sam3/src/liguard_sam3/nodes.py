"""
SAM3 Nodes for LiGuard-Web

This module provides nodes for integrating with the SAM3 segmentation model
via the SAM3 server REST API. All communication is done through HTTP requests,
keeping SAM3 dependencies completely separate.

Node Categories:
- Connection: Connect/disconnect from SAM3 server
- Image Segmentation: Set image, add prompts, get results
- Video Segmentation: Streaming video segmentation
- Utility: Create points, boxes, convert data formats
"""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from liguard_core import register_node, NodeBase, ExecutionContext
from liguard_core.node_spec import NodeSpec, ParamSpec, PortSpec
from liguard_core.typesystem import (
    t_any, t_boolean, t_box, t_control, t_float, t_int, 
    t_list, t_mask, t_point, t_session, t_string,
)


def _require_requests() -> None:
    if not REQUESTS_AVAILABLE:
        raise RuntimeError("requests library not installed. Please install with: pip install requests")


# =============================================================================
# Session Data Class
# =============================================================================

@dataclass
class SAM3Session:
    """Holds session information for communicating with SAM3 server."""
    server_url: str
    session_id: str
    model_type: str  # "image" or "video"
    timeout: int
    created_at: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation."""
        return {
            "_type": "SAM3Session",
            "server_url": self.server_url,
            "session_id": self.session_id,
            "model_type": self.model_type,
            "timeout": self.timeout,
            "created_at": self.created_at,
        }
    
    def _make_request(
        self, 
        method: str, 
        endpoint: str, 
        json_data: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Make a request to the SAM3 server."""
        _require_requests()
        url = f"{self.server_url.rstrip('/')}/{endpoint.lstrip('/')}"
        
        try:
            if method.upper() == "GET":
                response = requests.get(url, timeout=self.timeout)
            elif method.upper() == "POST":
                response = requests.post(url, json=json_data, timeout=self.timeout)
            elif method.upper() == "DELETE":
                response = requests.delete(url, timeout=self.timeout)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")
            
            response.raise_for_status()
            return response.json()
        except requests.exceptions.Timeout:
            raise TimeoutError(f"Request to {url} timed out after {self.timeout}s")
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"Could not connect to SAM3 server at {self.server_url}")
        except requests.exceptions.HTTPError as e:
            error_detail = ""
            try:
                error_detail = e.response.json().get("detail", str(e))
            except Exception:
                error_detail = str(e)
            raise RuntimeError(f"SAM3 server error: {error_detail}")


# =============================================================================
# Point and Box Data Classes
# =============================================================================

@dataclass
class Point:
    """A 2D point with optional positive/negative label."""
    x: float
    y: float
    is_positive: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "_type": "Point",
            "x": self.x,
            "y": self.y,
            "is_positive": self.is_positive,
        }


@dataclass
class Box:
    """A bounding box with optional positive/negative label."""
    x1: float
    y1: float
    x2: float
    y2: float
    is_positive: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "_type": "Box",
            "x1": self.x1,
            "y1": self.y1,
            "x2": self.x2,
            "y2": self.y2,
            "is_positive": self.is_positive,
        }


# =============================================================================
# Connection Nodes
# =============================================================================

SAM3_CONNECT_SPEC = NodeSpec(
    type="sam3.connect",
    version="1.0.0",
    display_name="Connect to SAM3",
    category="AI",
    summary="Create a session with a SAM3 server.",
    description="Connects to a SAM3 server and creates a new session for segmentation tasks.",
    icon="link",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
        PortSpec(name="model_type", type=t_string(), required=False, default="image"),
        PortSpec(name="timeout", type=t_int(), required=False, default=30),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="session_id", type=t_string()),
        PortSpec(name="connected", type=t_boolean()),
    ],
)


@register_node(SAM3_CONNECT_SPEC)
class SAM3ConnectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_requests()
        
        server_url = inputs.get("server_url", "http://localhost:8765")
        model_type = inputs.get("model_type", "image")
        timeout = int(inputs.get("timeout", 30))
        
        ctx.log(f"Connecting to SAM3 server at {server_url}")
        
        try:
            # Create session
            url = f"{server_url.rstrip('/')}/sessions"
            response = requests.post(
                url, 
                json={"model_type": model_type, "device": "cuda"},
                timeout=timeout
            )
            response.raise_for_status()
            data = response.json()
            
            session = SAM3Session(
                server_url=server_url,
                session_id=data["session_id"],
                model_type=model_type,
                timeout=timeout,
                created_at=time.time(),
            )
            
            ctx.log(f"Connected to SAM3: session_id={session.session_id}")
            
            # Register for cleanup
            if hasattr(ctx, "register_resource"):
                ctx.register_resource(session)
            
            return {
                "control_out": None,
                "session": session,
                "session_id": session.session_id,
                "connected": True,
            }
        except Exception as e:
            ctx.log(f"Failed to connect: {e}")
            return {
                "control_out": None,
                "session": None,
                "session_id": "",
                "connected": False,
            }


SAM3_DISCONNECT_SPEC = NodeSpec(
    type="sam3.disconnect",
    version="1.0.0",
    display_name="Disconnect SAM3",
    category="AI",
    summary="Close a SAM3 session.",
    description="Disconnects from a SAM3 server and releases resources.",
    icon="link-off",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="disconnected", type=t_boolean()),
    ],
)


@register_node(SAM3_DISCONNECT_SPEC)
class SAM3DisconnectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        
        if not session:
            return {"control_out": None, "disconnected": False}
        
        try:
            session._make_request("DELETE", f"/sessions/{session.session_id}")
            ctx.log(f"Disconnected SAM3 session: {session.session_id}")
            return {"control_out": None, "disconnected": True}
        except Exception as e:
            ctx.log(f"Error disconnecting: {e}")
            return {"control_out": None, "disconnected": False}


SAM3_HEARTBEAT_SPEC = NodeSpec(
    type="sam3.heartbeat",
    version="1.0.0",
    display_name="SAM3 Heartbeat",
    category="AI",
    summary="Keep a SAM3 session alive.",
    description="Sends a heartbeat to prevent session timeout.",
    icon="heart",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="alive", type=t_boolean()),
    ],
)


@register_node(SAM3_HEARTBEAT_SPEC)
class SAM3HeartbeatNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        
        if not session:
            return {"control_out": None, "session": None, "alive": False}
        
        try:
            session._make_request("POST", f"/sessions/{session.session_id}/heartbeat")
            return {"control_out": None, "session": session, "alive": True}
        except Exception:
            return {"control_out": None, "session": session, "alive": False}


# =============================================================================
# Image Segmentation Nodes
# =============================================================================

SAM3_SET_IMAGE_SPEC = NodeSpec(
    type="sam3.set_image",
    version="1.0.0",
    display_name="SAM3 Set Image",
    category="AI",
    summary="Set the image for segmentation.",
    description="Uploads an image to a SAM3 session for segmentation.",
    icon="image",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="image", type=t_string().with_nullable(True), required=True),  # base64
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_SET_IMAGE_SPEC)
class SAM3SetImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        image: str = inputs.get("image")
        
        if not session:
            raise ValueError("No session provided")
        if not image:
            raise ValueError("No image provided")
        
        result = session._make_request(
            "POST", 
            f"/image/{session.session_id}/set",
            {"image": image}
        )
        
        ctx.log(f"Image set: {result.get('width')}x{result.get('height')}")
        
        return {
            "control_out": None,
            "session": session,
            "width": result.get("width", 0),
            "height": result.get("height", 0),
        }


SAM3_PROMPT_TEXT_SPEC = NodeSpec(
    type="sam3.prompt_text",
    version="1.0.0",
    display_name="SAM3 Text Prompt",
    category="AI",
    summary="Add a text prompt for segmentation.",
    description="Sets a text prompt (e.g., 'person', 'car') to segment objects in the image.",
    icon="type",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="text", type=t_string(), required=True),
        PortSpec(name="confidence_threshold", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="objects_found", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_PROMPT_TEXT_SPEC)
class SAM3PromptTextNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        text = inputs.get("text") or self.params.get("text", "")
        confidence = inputs.get("confidence_threshold")
        if confidence is None:
            confidence = self.params.get("confidence_threshold", 0.5)
        
        if not session:
            raise ValueError("No session provided")
        if not text:
            raise ValueError("No text prompt provided")
        
        result = session._make_request(
            "POST",
            f"/image/{session.session_id}/prompt/text",
            {"text": text, "confidence_threshold": float(confidence)}
        )
        
        objects_found = result.get("objects_found", 0)
        ctx.log(f"Text prompt '{text}': found {objects_found} objects")
        
        return {
            "control_out": None,
            "session": session,
            "objects_found": objects_found,
        }


SAM3_PROMPT_BOX_SPEC = NodeSpec(
    type="sam3.prompt_box",
    version="1.0.0",
    display_name="SAM3 Box Prompt",
    category="AI",
    summary="Add a box prompt for segmentation.",
    description="Adds a bounding box prompt to include or exclude objects.",
    icon="square",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="box", type=t_box(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="objects_found", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_PROMPT_BOX_SPEC)
class SAM3PromptBoxNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        box: Box = inputs.get("box")
        
        if not session:
            raise ValueError("No session provided")
        if not box:
            raise ValueError("No box provided")
        
        result = session._make_request(
            "POST",
            f"/image/{session.session_id}/prompt/box",
            {
                "x1": box.x1,
                "y1": box.y1,
                "x2": box.x2,
                "y2": box.y2,
                "is_positive": box.is_positive,
            }
        )
        
        objects_found = result.get("objects_found", 0)
        ctx.log(f"Box prompt: found {objects_found} objects")
        
        return {
            "control_out": None,
            "session": session,
            "objects_found": objects_found,
        }


SAM3_PROMPT_POINT_SPEC = NodeSpec(
    type="sam3.prompt_point",
    version="1.0.0",
    display_name="SAM3 Point Prompt",
    category="AI",
    summary="Add a point prompt for segmentation.",
    description="Adds a point prompt to include or exclude objects.",
    icon="crosshair",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="point", type=t_point(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="objects_found", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_PROMPT_POINT_SPEC)
class SAM3PromptPointNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        point: Point = inputs.get("point")
        
        if not session:
            raise ValueError("No session provided")
        if not point:
            raise ValueError("No point provided")
        
        result = session._make_request(
            "POST",
            f"/image/{session.session_id}/prompt/point",
            {
                "x": point.x,
                "y": point.y,
                "is_positive": point.is_positive,
            }
        )
        
        objects_found = result.get("objects_found", 0)
        ctx.log(f"Point prompt: found {objects_found} objects")
        
        return {
            "control_out": None,
            "session": session,
            "objects_found": objects_found,
        }


SAM3_GET_RESULTS_SPEC = NodeSpec(
    type="sam3.get_results",
    version="1.0.0",
    display_name="SAM3 Get Results",
    category="AI",
    summary="Get segmentation results.",
    description="Retrieves masks, bounding boxes, and confidence scores from segmentation.",
    icon="download",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="masks", type=t_list(t_mask())),
        PortSpec(name="boxes", type=t_list(t_box())),
        PortSpec(name="scores", type=t_list(t_float())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_GET_RESULTS_SPEC)
class SAM3GetResultsNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        
        if not session:
            raise ValueError("No session provided")
        
        result = session._make_request("GET", f"/image/{session.session_id}/results")
        
        # Convert boxes to Box objects
        boxes = []
        for box_coords in result.get("boxes", []):
            if len(box_coords) >= 4:
                boxes.append(Box(
                    x1=box_coords[0],
                    y1=box_coords[1],
                    x2=box_coords[2],
                    y2=box_coords[3],
                ))
        
        count = result.get("count", 0)
        ctx.log(f"Retrieved {count} segmentation results")
        
        return {
            "control_out": None,
            "masks": result.get("masks", []),
            "boxes": boxes,
            "scores": result.get("scores", []),
            "count": count,
        }


SAM3_VISUALIZE_SPEC = NodeSpec(
    type="sam3.visualize",
    version="1.0.0",
    display_name="SAM3 Visualize",
    category="AI",
    summary="Get annotated image with segmentation overlay.",
    description="Returns the image with masks, boxes, and scores overlaid.",
    icon="eye",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="alpha", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_string()),  # base64
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VISUALIZE_SPEC)
class SAM3VisualizeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        alpha = inputs.get("alpha")
        if alpha is None:
            alpha = self.params.get("alpha", 0.5)
        
        if not session:
            raise ValueError("No session provided")
        
        result = session._make_request(
            "POST",
            f"/image/{session.session_id}/visualize",
            {"alpha": float(alpha)}
        )
        
        ctx.log("Generated visualization")
        
        return {
            "control_out": None,
            "image": result.get("image", ""),
        }


SAM3_RESET_SPEC = NodeSpec(
    type="sam3.reset",
    version="1.0.0",
    display_name="SAM3 Reset",
    category="AI",
    summary="Clear all prompts.",
    description="Resets the session to allow new prompts on the same image.",
    icon="refresh-cw",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
    ],
)


@register_node(SAM3_RESET_SPEC)
class SAM3ResetNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        
        if not session:
            raise ValueError("No session provided")
        
        session._make_request("POST", f"/image/{session.session_id}/reset")
        ctx.log("Reset prompts")
        
        return {
            "control_out": None,
            "session": session,
        }


# =============================================================================
# Video Segmentation Nodes
# =============================================================================

SAM3_VIDEO_START_SPEC = NodeSpec(
    type="sam3.video_start",
    version="1.0.0",
    display_name="SAM3 Video Start",
    category="AI",
    summary="Start a video segmentation session.",
    description="Initializes video mode for streaming or file-based video.",
    icon="video",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="streaming", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VIDEO_START_SPEC)
class SAM3VideoStartNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        streaming = inputs.get("streaming")
        if streaming is None:
            streaming = True
        
        if not session:
            raise ValueError("No session provided")
        
        session._make_request(
            "POST",
            f"/video/{session.session_id}/start",
            {"streaming": streaming}
        )
        
        ctx.log(f"Video session started (streaming={streaming})")
        
        return {
            "control_out": None,
            "session": session,
        }


SAM3_VIDEO_ADD_FRAME_SPEC = NodeSpec(
    type="sam3.video_add_frame",
    version="1.0.0",
    display_name="SAM3 Add Video Frame",
    category="AI",
    summary="Add a frame to a streaming video session.",
    description="Adds a frame for video segmentation. Use in a loop for streaming.",
    icon="film",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="image", type=t_string().with_nullable(True), required=True),  # base64
        PortSpec(name="frame_idx", type=t_int(), required=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VIDEO_ADD_FRAME_SPEC)
class SAM3VideoAddFrameNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        image = inputs.get("image")
        frame_idx = inputs.get("frame_idx")
        
        if not session:
            raise ValueError("No session provided")
        if not image:
            raise ValueError("No image provided")
        if frame_idx is None:
            raise ValueError("No frame_idx provided")
        
        session._make_request(
            "POST",
            f"/video/{session.session_id}/frame",
            {"image": image, "frame_idx": int(frame_idx)}
        )
        
        return {
            "control_out": None,
            "session": session,
        }


SAM3_VIDEO_PROMPT_SPEC = NodeSpec(
    type="sam3.video_prompt",
    version="1.0.0",
    display_name="SAM3 Video Prompt",
    category="AI",
    summary="Add a prompt to a video frame.",
    description="Adds a text or geometric prompt to a specific video frame.",
    icon="target",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="frame_idx", type=t_int(), required=True),
        PortSpec(name="text", type=t_string(), required=False, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VIDEO_PROMPT_SPEC)
class SAM3VideoPromptNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        frame_idx = inputs.get("frame_idx")
        text = inputs.get("text") or self.params.get("text", "")
        
        if not session:
            raise ValueError("No session provided")
        if frame_idx is None:
            raise ValueError("No frame_idx provided")
        
        data = {"frame_idx": int(frame_idx)}
        if text:
            data["text"] = text
        
        session._make_request(
            "POST",
            f"/video/{session.session_id}/prompt",
            data
        )
        
        ctx.log(f"Added prompt to frame {frame_idx}")
        
        return {
            "control_out": None,
            "session": session,
        }


SAM3_VIDEO_VISUALIZE_FRAME_SPEC = NodeSpec(
    type="sam3.video_visualize_frame",
    version="1.0.0",
    display_name="SAM3 Video Visualize Frame",
    category="AI",
    summary="Get annotated video frame.",
    description="Returns a video frame with segmentation overlay.",
    icon="eye",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="frame_idx", type=t_int(), required=True),
        PortSpec(name="alpha", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_string()),  # base64
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VIDEO_VISUALIZE_FRAME_SPEC)
class SAM3VideoVisualizeFrameNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        frame_idx = inputs.get("frame_idx")
        alpha = inputs.get("alpha", 0.5)
        
        if not session:
            raise ValueError("No session provided")
        if frame_idx is None:
            raise ValueError("No frame_idx provided")
        
        result = session._make_request(
            "POST",
            f"/video/{session.session_id}/visualize/{int(frame_idx)}",
            {"alpha": float(alpha)}
        )
        
        return {
            "control_out": None,
            "image": result.get("image", ""),
        }


# =============================================================================
# Utility Nodes
# =============================================================================

SAM3_CREATE_POINT_SPEC = NodeSpec(
    type="sam3.create_point",
    version="1.0.0",
    display_name="Create Point",
    category="AI",
    summary="Create a point from coordinates.",
    description="Creates a point with x, y coordinates (normalized 0-1) and label.",
    icon="crosshair",
    inputs=[
        PortSpec(name="x", type=t_float(), required=True, default=0.5),
        PortSpec(name="y", type=t_float(), required=True, default=0.5),
        PortSpec(name="is_positive", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="point", type=t_point()),
    ],
    params={
        "x": ParamSpec(name="x", type="float", label="X", default=0.5),
        "y": ParamSpec(name="y", type="float", label="Y", default=0.5),
        "is_positive": ParamSpec(name="is_positive", type="boolean", label="Positive", default=True),
    },
)


@register_node(SAM3_CREATE_POINT_SPEC)
class SAM3CreatePointNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        x = inputs.get("x")
        y = inputs.get("y")
        is_positive = inputs.get("is_positive")
        
        if x is None:
            x = self.params.get("x", 0.5)
        if y is None:
            y = self.params.get("y", 0.5)
        if is_positive is None:
            is_positive = self.params.get("is_positive", True)
        
        point = Point(x=float(x), y=float(y), is_positive=bool(is_positive))
        
        return {"point": point}


SAM3_CREATE_BOX_SPEC = NodeSpec(
    type="sam3.create_box",
    version="1.0.0",
    display_name="Create Box",
    category="AI",
    summary="Create a bounding box from coordinates.",
    description="Creates a box with x1, y1, x2, y2 coordinates (normalized 0-1) and label.",
    icon="square",
    inputs=[
        PortSpec(name="x1", type=t_float(), required=True, default=0.25),
        PortSpec(name="y1", type=t_float(), required=True, default=0.25),
        PortSpec(name="x2", type=t_float(), required=True, default=0.75),
        PortSpec(name="y2", type=t_float(), required=True, default=0.75),
        PortSpec(name="is_positive", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="box", type=t_box()),
    ],
    params={
        "x1": ParamSpec(name="x1", type="float", label="X1", default=0.25),
        "y1": ParamSpec(name="y1", type="float", label="Y1", default=0.25),
        "x2": ParamSpec(name="x2", type="float", label="X2", default=0.75),
        "y2": ParamSpec(name="y2", type="float", label="Y2", default=0.75),
        "is_positive": ParamSpec(name="is_positive", type="boolean", label="Positive", default=True),
    },
)


@register_node(SAM3_CREATE_BOX_SPEC)
class SAM3CreateBoxNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        x1 = inputs.get("x1") or self.params.get("x1", 0.25)
        y1 = inputs.get("y1") or self.params.get("y1", 0.25)
        x2 = inputs.get("x2") or self.params.get("x2", 0.75)
        y2 = inputs.get("y2") or self.params.get("y2", 0.75)
        is_positive = inputs.get("is_positive")
        if is_positive is None:
            is_positive = self.params.get("is_positive", True)
        
        box = Box(
            x1=float(x1),
            y1=float(y1),
            x2=float(x2),
            y2=float(y2),
            is_positive=bool(is_positive),
        )
        
        return {"box": box}


SAM3_BOX_TO_STRING_SPEC = NodeSpec(
    type="sam3.box_to_string",
    version="1.0.0",
    display_name="Box to String",
    category="AI",
    summary="Convert a box to a string representation.",
    description="Returns a human-readable string of box coordinates.",
    icon="type",
    inputs=[
        PortSpec(name="box", type=t_box(), required=True),
    ],
    outputs=[
        PortSpec(name="value", type=t_string()),
    ],
)


@register_node(SAM3_BOX_TO_STRING_SPEC)
class SAM3BoxToStringNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        box: Box = inputs.get("box")
        
        if not box:
            return {"value": ""}
        
        label = "positive" if box.is_positive else "negative"
        value = f"Box({box.x1:.3f}, {box.y1:.3f}, {box.x2:.3f}, {box.y2:.3f}, {label})"
        
        return {"value": value}


SAM3_SEGMENT_IMAGE_SPEC = NodeSpec(
    type="sam3.segment_image",
    version="1.0.0",
    display_name="SAM3 Segment Image",
    category="AI",
    summary="One-shot image segmentation with text prompt.",
    description="Combines set_image, prompt_text, and visualize into a single node for convenience.",
    icon="wand",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session(), required=True),
        PortSpec(name="image", type=t_string().with_nullable(True), required=True),  # base64
        PortSpec(name="text", type=t_string(), required=True),
        PortSpec(name="confidence_threshold", type=t_float(), required=False, default=0.5),
        PortSpec(name="alpha", type=t_float(), required=False, default=0.5),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session", type=t_session()),
        PortSpec(name="result_image", type=t_string()),  # base64
        PortSpec(name="count", type=t_int()),
        PortSpec(name="scores", type=t_list(t_float())),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_SEGMENT_IMAGE_SPEC)
class SAM3SegmentImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session: SAM3Session = inputs.get("session")
        image = inputs.get("image")
        text = inputs.get("text") or self.params.get("text", "")
        confidence = inputs.get("confidence_threshold")
        alpha = inputs.get("alpha")
        
        if confidence is None:
            confidence = self.params.get("confidence_threshold", 0.5)
        if alpha is None:
            alpha = self.params.get("alpha", 0.5)
        
        if not session:
            raise ValueError("No session provided")
        if not image:
            raise ValueError("No image provided")
        if not text:
            raise ValueError("No text prompt provided")
        
        # Set image
        ctx.log(f"Setting image for segmentation")
        session._make_request(
            "POST",
            f"/image/{session.session_id}/set",
            {"image": image}
        )
        
        # Add text prompt
        ctx.log(f"Segmenting with prompt: '{text}'")
        result = session._make_request(
            "POST",
            f"/image/{session.session_id}/prompt/text",
            {"text": text, "confidence_threshold": float(confidence)}
        )
        objects_found = result.get("objects_found", 0)
        
        # Get results for scores
        results = session._make_request("GET", f"/image/{session.session_id}/results")
        scores = results.get("scores", [])
        
        # Visualize
        viz_result = session._make_request(
            "POST",
            f"/image/{session.session_id}/visualize",
            {"alpha": float(alpha)}
        )
        
        ctx.log(f"Found {objects_found} objects")
        
        return {
            "control_out": None,
            "session": session,
            "result_image": viz_result.get("image", ""),
            "count": objects_found,
            "scores": scores,
        }
