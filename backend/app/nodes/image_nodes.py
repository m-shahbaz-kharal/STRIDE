"""Image loading and saving nodes."""
from __future__ import annotations

import base64
import os
from typing import Any, Dict
from urllib.error import URLError
from urllib.request import urlopen

from . import register_node
from .base import ExecutionContext, NodeBase
from ..node_spec import NodeSpec, PortSpec
from ..typesystem import t_boolean, t_control, t_string


# ============================================================================
# IMAGE OPERATIONS
# ============================================================================

LOAD_IMAGE_SPEC = NodeSpec(
    type="core.image.load",
    version="1.0.0",
    display_name="Load Image",
    category="Images",
    summary="Load an image from file or URL.",
    description="Reads an image from a local file path or URL and returns it as a base64 encoded string.",
    icon="image",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="file_path", type=t_string(), required=True, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_string()),
    ],
)


@register_node(LOAD_IMAGE_SPEC)
class LoadImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        file_path = str(inputs.get("file_path") or "")

        if not file_path:
            raise ValueError("No file path provided")

        try:
            # Check if it's a URL
            if file_path.startswith("http://") or file_path.startswith("https://"):
                ctx.log(f"Loading image from URL: {file_path}")
                with urlopen(file_path, timeout=30) as response:
                    image_data = response.read()
            else:
                # Local file path
                ctx.log(f"Loading image from file: {file_path}")
                if not os.path.exists(file_path):
                    raise FileNotFoundError(f"File not found: {file_path}")
                with open(file_path, "rb") as f:
                    image_data = f.read()

            # Determine MIME type from file extension or content
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".bmp": "image/bmp",
                ".webp": "image/webp",
            }
            mime_type = mime_map.get(ext, "image/jpeg")

            # Encode to base64 with data URL prefix
            base64_str = base64.b64encode(image_data).decode("utf-8")
            result = f"data:{mime_type};base64,{base64_str}"

            ctx.log(f"Loaded image ({len(image_data)} bytes)")
            return {"control_out": None, "image": result}

        except URLError as e:
            raise ConnectionError(f"Failed to fetch URL: {e}")
        except Exception as e:
            raise RuntimeError(f"Failed to load image: {e}")


SAVE_IMAGE_SPEC = NodeSpec(
    type="core.image.save",
    version="1.0.0",
    display_name="Save Image",
    category="Images",
    summary="Save a base64 image to file.",
    description="Decodes a base64 encoded image and saves it to the specified file path. Format is determined by file extension.",
    icon="save",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_string().with_nullable(True), required=True),  # base64
        PortSpec(name="file_path", type=t_string(), required=True, default=""),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="saved", type=t_boolean()),
        PortSpec(name="file_path", type=t_string()),
    ],
    cache_policy="disabled",
)


@register_node(SAVE_IMAGE_SPEC)
class SaveImageNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        image = inputs.get("image")
        file_path = str(inputs.get("file_path") or "")

        if not image:
            raise ValueError("No image provided")
        if not file_path:
            raise ValueError("No file path provided")

        try:
            # Handle data URL format
            if "," in image:
                image = image.split(",", 1)[1]

            # Decode base64
            image_data = base64.b64decode(image)

            # Create parent directories if needed
            parent_dir = os.path.dirname(file_path)
            if parent_dir and not os.path.exists(parent_dir):
                os.makedirs(parent_dir, exist_ok=True)

            # Write to file
            with open(file_path, "wb") as f:
                f.write(image_data)

            ctx.log(f"Saved image to {file_path} ({len(image_data)} bytes)")
            return {"control_out": None, "saved": True, "file_path": file_path}

        except Exception as e:
            ctx.log(f"Failed to save image: {e}")
            return {"control_out": None, "saved": False, "file_path": file_path}
