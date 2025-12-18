from __future__ import annotations

import base64
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
import uuid
from typing import Any, Dict, Optional, Tuple

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


def _get_fl511_stream_url(camera_id: int) -> str:
    """Headless Edge + performance log sniffing to extract HLS URL."""
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("Selenium is not installed. Please install it with: pip install selenium")

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
            except Exception:
                continue

        if not hls_url:
            raise RuntimeError(f"Could not get stream URL for camera {camera_id}")

        return hls_url
    finally:
        driver.quit()


def _probe_resolution(hls_url: str) -> Tuple[int, int]:
    """Probe HLS stream for width/height."""
    import re
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height",
        "-of", "default=noprint_wrappers=1",
        "-headers", "Origin: https://fl511.com\r\nReferer: https://fl511.com/\r\n",
        hls_url,
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        width_match = re.search(r"width=(\d+)", result.stdout)
        height_match = re.search(r"height=(\d+)", result.stdout)
        if width_match and height_match:
            return int(width_match.group(1)), int(height_match.group(1))
    except Exception:
        pass
    return 704, 480


class _StreamWorker:
    """Background ffmpeg reader that keeps a rolling queue of frames."""

    def __init__(self, stream_id: str, camera_id: int, hls_url: str, target_fps: int = 15, buffer_seconds: int = 4) -> None:
        if not CV2_AVAILABLE:
            raise RuntimeError("OpenCV is not installed. Please install it with: pip install opencv-python numpy")
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg.")

        self.stream_id = stream_id
        self.camera_id = camera_id
        self.hls_url = hls_url
        self.target_fps = target_fps
        self.buffer_frames = max(10, target_fps * buffer_seconds)
        self.width, self.height = _probe_resolution(hls_url)
        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=self.buffer_frames)
        self._running = threading.Event()
        self._running.set()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._proc: Optional[subprocess.Popen] = None

    def _ffmpeg_cmd(self) -> list[str]:
        return [
            "ffmpeg",
            "-headers", "Origin: https://fl511.com\r\nReferer: https://fl511.com/\r\n",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", self.hls_url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an", "-sn",
            "-vsync", "cfr",
            "-r", str(self.target_fps),
            "-",
        ]

    def start(self) -> None:
        self._proc = subprocess.Popen(
            self._ffmpeg_cmd(),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=10**7,
        )
        self._thread.start()

    def _reader_loop(self) -> None:
        assert self._proc and self._proc.stdout
        frame_size = self.width * self.height * 3
        while self._running.is_set():
            raw = b""
            while len(raw) < frame_size and self._running.is_set():
                chunk = self._proc.stdout.read(frame_size - len(raw))
                if not chunk:
                    break
                raw += chunk

            if len(raw) != frame_size:
                break

            frame = np.frombuffer(raw, dtype=np.uint8).reshape((self.height, self.width, 3))

            try:
                self._queue.put(frame, timeout=0.01)
            except queue.Full:
                try:
                    _ = self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put(frame, timeout=0.01)
                except queue.Full:
                    pass

        self._running.clear()

    def stop(self) -> None:
        self._running.clear()
        if self._proc:
            self._proc.terminate()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def latest_frame(self, timeout: float = 0.1) -> Optional[np.ndarray]:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None


class CameraStreamManager:
    """Registry of live camera streams shared across nodes."""

    def __init__(self) -> None:
        self._streams: Dict[str, _StreamWorker] = {}
        self._lock = threading.Lock()

    def start_stream(self, camera_id: int, target_fps: int = 15, buffer_seconds: int = 4) -> Tuple[str, _StreamWorker]:
        hls_url = _get_fl511_stream_url(camera_id)
        stream_id = str(uuid.uuid4())[:8]
        worker = _StreamWorker(stream_id, camera_id, hls_url, target_fps=target_fps, buffer_seconds=buffer_seconds)
        worker.start()
        with self._lock:
            self._streams[stream_id] = worker
        return stream_id, worker

    def get_stream(self, stream_id: str) -> _StreamWorker:
        with self._lock:
            if stream_id not in self._streams:
                raise KeyError(f"Unknown stream '{stream_id}'")
            return self._streams[stream_id]

    def stop_stream(self, stream_id: str) -> bool:
        with self._lock:
            worker = self._streams.pop(stream_id, None)
        if worker:
            worker.stop()
            return True
        return False

    def stop_all(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for worker in streams:
            worker.stop()


STREAM_MANAGER = CameraStreamManager()


@register_node
class GetStreamURLNode(NodeBase):
    """Gets HLS stream URL from FL511 camera using Selenium."""

    node_type = "camera.get_stream_url"
    display_name = "Get Camera Stream URL"
    description = "Retrieves HLS stream URL from fl511.com for a given camera ID using Selenium."
    icon = "camera"
    input_ports = []
    output_ports = ["url"]
    output_port_types = {"url": "url"}
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
        camera_id = int(self.params.get("camera_id", 2130))
        ctx.log(f"Getting stream URL for camera {camera_id}...")
        hls_url = _get_fl511_stream_url(camera_id)
        ctx.log(f"Found stream URL: {hls_url[:80]}...")
        return {"url": hls_url}


@register_node
class ReadFrameNode(NodeBase):
    """Reads a single frame from an HLS stream URL using ffmpeg."""

    node_type = "camera.read_frame"
    display_name = "Read Camera Frame"
    description = "Reads a single frame from an HLS stream URL and outputs it as a base64-encoded image."
    icon = "image"
    input_ports = ["url"]
    output_ports = ["image", "width", "height"]
    input_port_types = {"url": "url"}
    output_port_types = {"image": "image", "width": "number", "height": "number"}
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
        return _probe_resolution(hls_url)

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
class StartCameraStreamNode(NodeBase):
    """Starts a background camera stream and returns a stream id for polling frames."""

    node_type = "camera.stream_start"
    display_name = "Start Camera Stream"
    description = "Launches a live FL511 stream reader in the background."
    icon = "camera"
    input_ports: list[str] = []
    output_ports = ["stream_id", "url", "width", "height", "fps"]
    output_port_types = {
        "stream_id": "stream",
        "url": "url",
        "width": "number",
        "height": "number",
        "fps": "number",
    }
    params_schema = {
        "camera_id": {
            "type": "number",
            "label": "Camera ID",
            "description": "FL511 camera ID (e.g., 2130)",
            "default": 2130,
        },
        "target_fps": {
            "type": "number",
            "label": "Target FPS",
            "description": "Decode at this frame rate.",
            "default": 15,
        },
        "buffer_seconds": {
            "type": "number",
            "label": "Buffer Seconds",
            "description": "Seconds of frames to keep buffered.",
            "default": 4,
        },
    }

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        camera_id = int(self.params.get("camera_id", 2130))
        target_fps = int(self.params.get("target_fps", 15))
        buffer_seconds = int(self.params.get("buffer_seconds", 4))
        ctx.log(f"Starting stream for camera {camera_id} @ {target_fps}fps")
        stream_id, worker = STREAM_MANAGER.start_stream(camera_id, target_fps=target_fps, buffer_seconds=buffer_seconds)
        ctx.log(f"Stream {stream_id} started with resolution {worker.width}x{worker.height}")
        return {
            "stream_id": stream_id,
            "url": worker.hls_url,
            "width": worker.width,
            "height": worker.height,
            "fps": target_fps,
        }


@register_node
class NextCameraFrameNode(NodeBase):
    """Polls the latest frame from a running camera stream."""

    node_type = "camera.stream_frame"
    display_name = "Camera Frame"
    description = "Fetches the next frame from a live stream (non-blocking)."
    icon = "image"
    input_ports = ["stream_id"]
    output_ports = ["image", "width", "height", "timestamp"]
    input_port_types = {"stream_id": "stream"}
    output_port_types = {
        "image": "image",
        "width": "number",
        "height": "number",
        "timestamp": "number",
    }
    params_schema = {
        "timeout": {
            "type": "number",
            "label": "Timeout (seconds)",
            "description": "How long to wait for a frame before failing.",
            "default": 0.2,
        }
    }

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        stream_id = inputs.get("stream_id")
        if not stream_id:
            raise ValueError("Missing required input: stream_id")
        timeout = float(self.params.get("timeout", 0.2))

        worker = STREAM_MANAGER.get_stream(str(stream_id))
        frame = worker.latest_frame(timeout=timeout)
        if frame is None:
            raise TimeoutError(f"No frame available within {timeout}s")

        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        _, buffer = cv2.imencode(".jpg", frame_rgb, [cv2.IMWRITE_JPEG_QUALITY, 85])
        image_base64 = base64.b64encode(buffer).decode("utf-8")
        image_data_url = f"data:image/jpeg;base64,{image_base64}"

        ctx.log(f"Fetched frame from stream {stream_id}")
        return {
            "image": image_data_url,
            "width": worker.width,
            "height": worker.height,
            "timestamp": time.time(),
        }


@register_node
class StopCameraStreamNode(NodeBase):
    """Stops a running camera stream."""

    node_type = "camera.stream_stop"
    display_name = "Stop Camera Stream"
    description = "Stops a live stream and releases resources."
    icon = "stop"
    input_ports = ["stream_id"]
    output_ports = ["stopped"]
    input_port_types = {"stream_id": "stream"}
    output_port_types = {"stopped": "boolean"}
    params_schema: Dict[str, Any] = {}

    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        stream_id = inputs.get("stream_id")
        if not stream_id:
            raise ValueError("Missing required input: stream_id")
        stopped = STREAM_MANAGER.stop_stream(str(stream_id))
        ctx.log(f"Stopped stream {stream_id}: {stopped}")
        return {"stopped": stopped}


@register_node
class DisplayImageNode(NodeBase):
    """Display node that accepts an image input and stores it for display in the outputs tab."""

    node_type = "display.image"
    display_name = "Display Image"
    description = "Takes an image input and displays it in the outputs tab. Accepts base64-encoded image data URLs."
    icon = "monitor"
    input_ports = ["image"]
    output_ports = ["display"]
    input_port_types = {"image": "image"}
    output_port_types = {"display": "image"}
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
