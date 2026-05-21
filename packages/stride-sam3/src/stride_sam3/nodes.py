"""
SAM3 Nodes for LiGuard-Web

This module provides unified nodes for integrating with the SAM3 segmentation model
via the SAM3 server REST API. All communication is done through HTTP requests,
keeping SAM3 dependencies completely separate.

Unified Nodes:
- SAM3 Connect: Create a session and return session_id
- SAM3 Is Alive: Check if session is alive
- SAM3 Set Prompt: Set text prompt (queues if no images)
- SAM3 Add Image: Add image/frame for segmentation
- SAM3 Get Output: Get raw segmentation outputs
- SAM3 Visualize: Get visualization of results
- SAM3 Disconnect: Close session and cleanup
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import requests
    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False

from stride_core import register_node, NodeBase, ExecutionContext
from stride_core.errors import (
    NodeInputError,
    NodeMissingDependencyError,
    NodeNetworkError,
)
from stride_core.node_spec import NodeSpec, PortSpec
from stride_core.typesystem import (
    t_any, t_boolean, t_control, t_float, t_int,
    t_list, t_string,
)


def _require_requests() -> None:
    if not REQUESTS_AVAILABLE:
        raise NodeMissingDependencyError(
            "requests library not installed. Please install with: pip install requests"
        )


def _make_request(
    server_url: str,
    method: str,
    endpoint: str,
    json_data: Optional[Dict] = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """Make a request to the SAM3 server."""
    _require_requests()
    url = f"{server_url.rstrip('/')}/{endpoint.lstrip('/')}"

    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(url, json=json_data, timeout=timeout)
        elif method.upper() == "DELETE":
            response = requests.delete(url, timeout=timeout)
        else:
            raise NodeInputError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()
    except requests.exceptions.Timeout as exc:
        raise NodeNetworkError(f"Request to {url} timed out after {timeout}s") from exc
    except requests.exceptions.ConnectionError as exc:
        raise NodeNetworkError(f"Could not connect to SAM3 server at {server_url}") from exc
    except requests.exceptions.HTTPError as e:
        error_detail = ""
        try:
            error_detail = e.response.json().get("detail", str(e))
        except Exception:
            error_detail = str(e)
        raise NodeNetworkError(f"SAM3 server error: {error_detail}") from e


# =============================================================================
# SAM3 - Connect
# =============================================================================

SAM3_CONNECT_SPEC = NodeSpec(
    type="sam3.connect",
    version="2.0.0",
    display_name="SAM3 - Connect",
    category="AI",
    summary="Connect to a SAM3 server and create a session.",
    description="Connects to a SAM3 server, loads the specified model, and returns a session ID. Returns empty string on failure.",
    icon="link",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
        PortSpec(name="model_type", type=t_string(), required=False, default="image", ui={
            "control": "select",
            "options": [{"label": "Image", "value": "image"}, {"label": "Video", "value": "video"}]
        }),
        PortSpec(name="timeout", type=t_int(), required=False, default=30),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_CONNECT_SPEC)
class SAM3ConnectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        _require_requests()
        
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        model_type = inputs.get("model_type")
        model_type = model_type if model_type is not None else "image"
        timeout = int(inputs.get("timeout") if inputs.get("timeout") is not None else 30)
        
        ctx.log(f"Connecting to SAM3 server at {server_url}")
        
        try:
            result = _make_request(
                server_url,
                "POST",
                "/api/connect",
                {"model_type": model_type, "timeout": timeout, "device": "cuda"},
                timeout=timeout
            )
            
            session_id = result.get("session_id", "")
            error = result.get("error", "")
            
            if error:
                ctx.log(f"Connection failed: {error}")
                return {"control_out": None, "session_id": ""}
            
            ctx.log(f"Connected to SAM3: session_id={session_id}")
            
            # Store server_url in context for other nodes
            if hasattr(ctx, "set_metadata"):
                ctx.set_metadata(f"sam3_server_{session_id}", server_url)
            
            return {"control_out": None, "session_id": session_id}
        except Exception as e:
            ctx.log(f"Failed to connect: {e}")
            return {"control_out": None, "session_id": ""}


# =============================================================================
# SAM3 - Is Alive
# =============================================================================

SAM3_IS_ALIVE_SPEC = NodeSpec(
    type="sam3.is_alive",
    version="2.0.0",
    display_name="SAM3 - Is Alive",
    category="AI",
    summary="Check if a SAM3 session is alive.",
    description="Checks if the session is valid and refreshes its expiry timer.",
    icon="heart",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
        PortSpec(name="alive", type=t_boolean()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_IS_ALIVE_SPEC)
class SAM3IsAliveNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            return {"control_out": None, "session_id": "", "alive": False}
        
        try:
            result = _make_request(
                server_url,
                "GET",
                f"/api/{session_id}/is-alive",
                timeout=10
            )
            alive = result.get("alive", False)
            return {"control_out": None, "session_id": session_id, "alive": alive}
        except Exception:
            return {"control_out": None, "session_id": session_id, "alive": False}


# =============================================================================
# SAM3 - Set Prompt
# =============================================================================

# =============================================================================
# SAM3 - Set Prompt
# =============================================================================

SAM3_SET_PROMPT_SPEC = NodeSpec(
    type="sam3.set_prompt",
    version="2.0.0",
    display_name="SAM3 - Set Prompt",
    category="AI",
    summary="Set the text prompt for segmentation.",
    description="Sets a text prompt (e.g., 'person', 'car'). Queues the prompt if no image has been added yet.",
    icon="type",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="prompt", type=t_string(), required=True),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_SET_PROMPT_SPEC)
class SAM3SetPromptNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        prompt = inputs.get("prompt", "")
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            raise NodeInputError("No session_id provided", port="session_id")
        if not prompt:
            raise NodeInputError("No prompt provided", port="prompt")
        
        result = _make_request(
            server_url,
            "POST",
            f"/api/{session_id}/set-prompt",
            {"prompt": prompt},
        )
        
        queued = result.get("queued", False)
        if queued:
            ctx.log(f"Prompt '{prompt}' queued (waiting for images)")
        else:
            ctx.log(f"Prompt '{prompt}' applied")
        
        return {"control_out": None, "session_id": result.get("session_id", session_id)}


# =============================================================================
# SAM3 - Add Image
# =============================================================================

SAM3_ADD_IMAGE_SPEC = NodeSpec(
    type="sam3.add_image",
    version="2.0.0",
    display_name="SAM3 - Add Image",
    category="AI",
    summary="Add an image for segmentation.",
    description="Adds an image or video frame. For video mode with batch>1, creates a sliding window buffer.",
    icon="image",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="image", type=t_string().with_nullable(True), required=True),  # base64
        PortSpec(name="batch", type=t_int(), required=False, default=1),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
        PortSpec(name="added", type=t_boolean()),
        PortSpec(name="frame_idx", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_ADD_IMAGE_SPEC)
class SAM3AddImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        image = inputs.get("image")
        batch = int(inputs.get("batch") if inputs.get("batch") is not None else 1)
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            raise NodeInputError("No session_id provided", port="session_id")
        if not image:
            raise NodeInputError("No image provided", port="image")
        
        result = _make_request(
            server_url,
            "POST",
            f"/api/{session_id}/add-image",
            {"image": image, "batch": batch},
        )
        
        added = result.get("added", False)
        frame_idx = result.get("frame_idx", 0)
        
        if added:
            ctx.log(f"Image added and processed (frame_idx={frame_idx})")
        else:
            ctx.log(f"Image buffered in batch (frame_idx={frame_idx})")
        
        return {
            "control_out": None,
            "session_id": result.get("session_id", session_id),
            "added": added,
            "frame_idx": frame_idx,
        }


# =============================================================================
# SAM3 - Get Output
# =============================================================================

SAM3_GET_OUTPUT_SPEC = NodeSpec(
    type="sam3.get_output",
    version="2.0.0",
    display_name="SAM3 - Get Output",
    category="AI",
    summary="Get raw segmentation outputs.",
    description="Returns masks, bounding boxes, and confidence scores for a specific frame.",
    icon="download",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="frame_idx", type=t_int(), required=False, default=0),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
        PortSpec(name="masks", type=t_list(t_string())),  # base64 encoded
        PortSpec(name="boxes", type=t_list(t_any())),
        PortSpec(name="scores", type=t_list(t_float())),
        PortSpec(name="count", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_GET_OUTPUT_SPEC)
class SAM3GetOutputNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        frame_idx = int(inputs.get("frame_idx") if inputs.get("frame_idx") is not None else 0)
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            raise NodeInputError("No session_id provided", port="session_id")
        
        result = _make_request(
            server_url,
            "GET",
            f"/api/{session_id}/get-output/{frame_idx}",
        )
        
        count = result.get("count", 0)
        ctx.log(f"Retrieved {count} segmentation results for frame {frame_idx}")
        
        return {
            "control_out": None,
            "session_id": result.get("session_id", session_id),
            "masks": result.get("masks", []),
            "boxes": result.get("boxes", []),
            "scores": result.get("scores", []),
            "count": count,
        }


# =============================================================================
# SAM3 - Visualize
# =============================================================================

SAM3_VISUALIZE_SPEC = NodeSpec(
    type="sam3.visualize",
    version="2.0.0",
    display_name="SAM3 - Visualize",
    category="AI",
    summary="Get visualization of segmentation results.",
    description="Returns an image with masks, boxes, and scores overlaid.",
    icon="eye",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="frame_idx", type=t_int(), required=False, default=0),
        PortSpec(name="alpha", type=t_float(), required=False, default=0.5),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string()),
        PortSpec(name="image", type=t_string()),  # base64
    ],
    cache_policy="disabled",
)


@register_node(SAM3_VISUALIZE_SPEC)
class SAM3VisualizeNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        frame_idx = int(inputs.get("frame_idx") if inputs.get("frame_idx") is not None else 0)
        alpha = float(inputs.get("alpha") if inputs.get("alpha") is not None else 0.5)
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            raise NodeInputError("No session_id provided", port="session_id")
        
        result = _make_request(
            server_url,
            "POST",
            f"/api/{session_id}/visualize",
            {"frame_idx": int(frame_idx), "alpha": float(alpha)},
        )
        
        ctx.log("Generated visualization")
        
        return {
            "control_out": None,
            "session_id": result.get("session_id", session_id),
            "image": result.get("image", ""),
        }


# =============================================================================
# SAM3 - Disconnect
# =============================================================================

SAM3_DISCONNECT_SPEC = NodeSpec(
    type="sam3.disconnect",
    version="2.0.0",
    display_name="SAM3 - Disconnect",
    category="AI",
    summary="Disconnect from SAM3 and cleanup.",
    description="Closes the session and releases all resources.",
    icon="link-off",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="session_id", type=t_string(), required=True),
        PortSpec(name="server_url", type=t_string(), required=False, default="http://localhost:8765"),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="disconnected", type=t_boolean()),
    ],
    cache_policy="disabled",
)


@register_node(SAM3_DISCONNECT_SPEC)
class SAM3DisconnectNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        session_id = inputs.get("session_id", "")
        server_url = inputs.get("server_url")
        server_url = server_url if server_url is not None else "http://localhost:8765"
        
        if not session_id:
            return {"control_out": None, "disconnected": False}
        
        try:
            result = _make_request(
                server_url,
                "DELETE",
                f"/api/{session_id}/disconnect",
            )
            disconnected = result.get("disconnected", False)
            if disconnected:
                ctx.log(f"Disconnected SAM3 session: {session_id}")
            return {"control_out": None, "disconnected": disconnected}
        except Exception as e:
            ctx.log(f"Error disconnecting: {e}")
            return {"control_out": None, "disconnected": False}
