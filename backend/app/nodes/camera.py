from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import time
from typing import Any, Dict

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False

try:
    from selenium import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.edge.options import Options
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False

from .base import ExecutionContext, NodeBase
from . import register_node


@register_node
class GetStreamURLNode(NodeBase):
    """Gets HLS stream URL from FL511 camera using Selenium."""

    node_type = "camera.get_stream_url"
    display_name = "Get Camera Stream URL"
    description = "Retrieves HLS stream URL from fl511.com for a given camera ID using Selenium."
    icon = "camera"
    input_ports = []
    output_ports = ["url"]
    params_schema = {
        "camera_id": {
            "type": "number",
            "label": "Camera ID",
            "description": "FL511 camera ID (e.g., 2130)",
            "default": 2130,
        }
    }

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        if not SELENIUM_AVAILABLE:
            raise RuntimeError("Selenium is not installed. Please install it with: pip install selenium")

        camera_id = int(self.params.get("camera_id", 2130))
        ctx.log(f"Getting stream URL for camera {camera_id}...")

        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--disable-gpu")
        options.add_argument("--log-level=3")
        options.add_argument("--disable-logging")
        options.add_experimental_option("excludeSwitches", ["enable-logging", "enable-automation"])
        options.set_capability("ms:loggingPrefs", {"performance": "ALL"})

        from selenium.webdriver.edge.service import Service
        service = Service(log_output=os.devnull)
        driver = webdriver.Edge(service=service, options=options)

        hls_url = None
        try:
            driver.get(f"https://fl511.com/#camera-{camera_id}")
            time.sleep(3)

            button = WebDriverWait(driver, 15).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, f"button.showVideo[data-camera-id='{camera_id}']"))
            )
            button.click()
            time.sleep(4)

            for entry in driver.get_log("performance"):
                try:
                    msg = json.loads(entry["message"])["message"]
                    if msg.get("method") == "Network.requestWillBeSent":
                        url = msg.get("params", {}).get("request", {}).get("url", "")
                        if "index.m3u8" in url and "token=" in url:
                            hls_url = url
                            break
                except:
                    pass

            if not hls_url:
                raise RuntimeError(f"Could not get stream URL for camera {camera_id}")

            ctx.log(f"Found stream URL: {hls_url[:80]}...")
            return {"url": hls_url}

        finally:
            driver.quit()


@register_node
class ReadFrameNode(NodeBase):
    """Reads a single frame from an HLS stream URL using ffmpeg."""

    node_type = "camera.read_frame"
    display_name = "Read Camera Frame"
    description = "Reads a single frame from an HLS stream URL and outputs it as a base64-encoded image."
    icon = "image"
    input_ports = ["url"]
    output_ports = ["image", "width", "height"]
    params_schema = {
        "timeout": {
            "type": "number",
            "label": "Timeout (seconds)",
            "description": "Maximum time to wait for frame",
            "default": 10,
        }
    }

    def _get_stream_resolution(self, hls_url: str) -> tuple[int, int]:
        """Probe stream to get actual resolution."""
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height",
            "-of", "default=noprint_wrappers=1",
            "-headers", "Origin: https://fl511.com\r\nReferer: https://fl511.com/\r\n",
            hls_url
        ]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            width_match = re.search(r'width=(\d+)', result.stdout)
            height_match = re.search(r'height=(\d+)', result.stdout)
            if width_match and height_match:
                return int(width_match.group(1)), int(height_match.group(1))
        except:
            pass
        # Fallback to default if probe fails
        return 704, 480

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV is not installed. Please install it with: pip install opencv-python numpy")

        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg.")

        hls_url = inputs.get("url")
        if not hls_url:
            raise ValueError("Missing required input: url")

        timeout = int(self.params.get("timeout", 10))
        ctx.log(f"Reading frame from stream (timeout: {timeout}s)...")

        # Get stream resolution
        width, height = self._get_stream_resolution(hls_url)
        ctx.log(f"Stream resolution: {width}x{height}")

        # Start ffmpeg to read a single frame
        frame_size = width * height * 3
        cmd = [
            "ffmpeg",
            "-headers", "Origin: https://fl511.com\r\nReferer: https://fl511.com/\r\n",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", hls_url,
            "-frames:v", "1",  # Read only 1 frame
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an", "-sn",
            "-"
        ]

        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=frame_size
            )

            # Read frame data
            raw = b''
            start_time = time.time()
            while len(raw) < frame_size:
                if time.time() - start_time > timeout:
                    proc.terminate()
                    raise TimeoutError(f"Timeout waiting for frame after {timeout}s")
                
                chunk = proc.stdout.read(frame_size - len(raw))
                if not chunk:
                    break
                raw += chunk

            if len(raw) != frame_size:
                proc.terminate()
                raise RuntimeError(f"Failed to read complete frame (got {len(raw)}/{frame_size} bytes)")

            # Convert to numpy array and then to image
            frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
            
            # Convert BGR to RGB for web display
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Encode as JPEG base64
            _, buffer = cv2.imencode('.jpg', frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
            image_base64 = base64.b64encode(buffer).decode('utf-8')
            image_data_url = f"data:image/jpeg;base64,{image_base64}"

            ctx.log(f"Successfully read frame: {width}x{height}")
            return {
                "image": image_data_url,
                "width": width,
                "height": height,
            }

        except subprocess.TimeoutExpired:
            raise TimeoutError(f"ffmpeg timeout after {timeout}s")
        except Exception as e:
            raise RuntimeError(f"Failed to read frame: {str(e)}")


@register_node
class DisplayImageNode(NodeBase):
    """Display node that accepts an image input and stores it for display in the outputs tab."""

    node_type = "display.image"
    display_name = "Display Image"
    description = "Takes an image input and displays it in the outputs tab. Accepts base64-encoded image data URLs."
    icon = "monitor"
    input_ports = ["image"]
    output_ports = ["display"]
    params_schema = {}

    def forward(
        self, inputs: Dict[str, Any], ctx: ExecutionContext
    ) -> Dict[str, Any]:
        image = inputs.get("image")
        if not image:
            raise ValueError("Missing required input: image")

        # Validate that it's a data URL or base64 string
        if isinstance(image, str):
            if image.startswith("data:image"):
                ctx.log("Received image data URL")
            elif image.startswith("/9j/") or len(image) > 100:
                # Likely base64 JPEG data, convert to data URL
                image = f"data:image/jpeg;base64,{image}"
                ctx.log("Converted base64 string to data URL")
            else:
                ctx.log(f"Received image string (length: {len(image)})")
        else:
            raise ValueError(f"Invalid image input type: {type(image)}")

        # Return the image for display
        return {"display": image}

