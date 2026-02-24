from __future__ import annotations

import base64
import json
import os
import queue
import shutil
import subprocess
import threading
import time
import uuid
from collections import deque
from typing import Any, Dict, Optional, Tuple

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

try:
    import cv2
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

from liguard_core import register_node, NodeBase, ExecutionContext
from liguard_core.node_spec import NodeSpec, PortSpec
from liguard_core.typesystem import t_boolean, t_control, t_float, t_int, t_string, t_stream


def _require_numpy() -> None:
    if not NUMPY_AVAILABLE:
        raise RuntimeError("numpy is not installed. Please install it with: pip install numpy")


def _require_cv2() -> None:
    if not CV2_AVAILABLE:
        raise RuntimeError("OpenCV is not installed. Please install it with: pip install opencv-python")


def _require_selenium() -> None:
    if not SELENIUM_AVAILABLE:
        raise RuntimeError("Selenium is not installed. Please install it with: pip install selenium")


def _resolve_fl511_hls_url(camera_id: int) -> str:
    _require_selenium()

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
            raise RuntimeError(f"Could not resolve stream URL for camera {camera_id}")
        return hls_url
    finally:
        driver.quit()


def _probe_stream_resolution(hls_url: str) -> Tuple[int, int]:
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
        width = None
        height = None
        for line in result.stdout.splitlines():
            if line.startswith("width="):
                width = int(line.split("=", 1)[1])
            elif line.startswith("height="):
                height = int(line.split("=", 1)[1])
        if width and height:
            return width, height
    except Exception:
        pass
    return 704, 480


ACTIVE_STREAMS: Dict[str, "StreamResource"] = {}


def get_active_stream(stream_id: str) -> Optional["StreamResource"]:
    return ACTIVE_STREAMS.get(stream_id)


class StreamResource:
    """A self-contained stream resource that manages its own ffmpeg process.

    Supports automatic token refresh: when *camera_id* is provided, a background
    thread periodically re-resolves the HLS URL (which carries a time-limited
    token) and seamlessly swaps the underlying ffmpeg process so the frame queue
    is never starved.
    """

    def __init__(
        self,
        stream_id: str,
        hls_url: str,
        target_fps: int,
        buffer_seconds: int,
        camera_id: Optional[int] = None,
        refresh_minutes: int = 4,
    ) -> None:
        _require_numpy()
        if not shutil.which("ffmpeg"):
            raise RuntimeError("ffmpeg not found in PATH. Please install ffmpeg.")

        self.stream_id = stream_id
        self.hls_url = hls_url
        self.target_fps = max(1, int(target_fps))
        self.buffer_frames = max(10, self.target_fps * max(1, int(buffer_seconds)))
        self.width, self.height = _probe_stream_resolution(hls_url)
        self.camera_id = camera_id
        self._refresh_interval: int = (
            max(60, int(refresh_minutes) * 60)
            if camera_id is not None and int(refresh_minutes) > 0
            else 0
        )

        self._queue: queue.Queue[np.ndarray] = queue.Queue(maxsize=self.buffer_frames)
        self._running = threading.Event()
        self._running.set()
        self._proc: Optional[subprocess.Popen] = None
        self._last_frame_time = 0.0
        self._lock = threading.Lock()
        self._stderr_lines: deque[str] = deque(maxlen=20)
        self._stderr_lock = threading.Lock()
        self._ffmpeg_exit_code: Optional[int] = None

        # Token refresh state
        self._pending_url: Optional[str] = None
        self._pending_url_lock = threading.Lock()
        self._swap_requested = threading.Event()

        ACTIVE_STREAMS[self.stream_id] = self

        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()

        self._refresher_thread: Optional[threading.Thread] = None
        if self._refresh_interval > 0:
            self._refresher_thread = threading.Thread(
                target=self._refresher_loop, daemon=True
            )
            self._refresher_thread.start()

    # ------------------------------------------------------------------
    # ffmpeg helpers
    # ------------------------------------------------------------------

    def _ffmpeg_cmd(self, url: Optional[str] = None) -> list[str]:
        return [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "error",
            "-headers", "Origin: https://fl511.com\r\nReferer: https://fl511.com/\r\n",
            "-reconnect", "1",
            "-reconnect_streamed", "1",
            "-reconnect_delay_max", "5",
            "-i", url or self.hls_url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-an", "-sn",
            "-vsync", "cfr",
            "-r", str(self.target_fps),
            "-",
        ]

    def _start_ffmpeg(self, url: Optional[str] = None) -> subprocess.Popen:
        proc = subprocess.Popen(
            self._ffmpeg_cmd(url),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**7,
        )
        threading.Thread(
            target=self._stderr_loop, args=(proc,), daemon=True
        ).start()
        return proc

    @staticmethod
    def _kill_proc(proc: subprocess.Popen) -> None:
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _stderr_loop(self, proc: subprocess.Popen) -> None:
        assert proc.stderr
        while True:
            line = proc.stderr.readline()
            if not line:
                break
            try:
                text = line.decode("utf-8", "replace").strip()
            except Exception:
                text = ""
            if text:
                with self._stderr_lock:
                    self._stderr_lines.append(text)
        exit_code = proc.poll()
        if exit_code is not None:
            self._ffmpeg_exit_code = exit_code

    # ------------------------------------------------------------------
    # Proactive token refresh
    # ------------------------------------------------------------------

    def _refresher_loop(self) -> None:
        """Periodically re-resolve the HLS URL before the token expires."""
        while self._running.is_set():
            elapsed = 0
            while elapsed < self._refresh_interval and self._running.is_set():
                time.sleep(1)
                elapsed += 1
            if not self._running.is_set():
                return
            try:
                new_url = _resolve_fl511_hls_url(self.camera_id)
                with self._pending_url_lock:
                    self._pending_url = new_url
                self._swap_requested.set()
            except Exception:
                pass  # keep current stream; will retry next interval

    # ------------------------------------------------------------------
    # Frame reader (with auto-restart)
    # ------------------------------------------------------------------

    def _reader_loop(self) -> None:
        """Start ffmpeg, read frames, and restart on swap or unexpected death."""
        while self._running.is_set():
            # Use a pre-resolved URL if available, otherwise the current one
            url = self.hls_url
            with self._pending_url_lock:
                if self._pending_url:
                    url = self._pending_url
                    self.hls_url = self._pending_url
                    self._pending_url = None
            self._swap_requested.clear()

            proc = self._start_ffmpeg(url)
            with self._lock:
                self._proc = proc

            self._read_frames(proc)
            self._kill_proc(proc)

            if not self._running.is_set():
                break

            # A proactive swap already has a pending URL ready — loop back
            if self._swap_requested.is_set():
                continue

            # ffmpeg died unexpectedly — try a reactive re-resolve
            if self.camera_id is not None:
                try:
                    self.hls_url = _resolve_fl511_hls_url(self.camera_id)
                    continue
                except Exception:
                    pass

            # Cannot recover
            self._running.clear()

    def _read_frames(self, proc: subprocess.Popen) -> None:
        assert proc.stdout
        frame_size = self.width * self.height * 3
        while self._running.is_set():
            # Let the outer loop swap to a fresh ffmpeg process
            if self._swap_requested.is_set():
                return

            raw = b""
            while len(raw) < frame_size and self._running.is_set():
                chunk = proc.stdout.read(frame_size - len(raw))
                if not chunk:
                    return  # process exited
                raw += chunk

            if len(raw) != frame_size:
                return

            frame = np.frombuffer(raw, dtype=np.uint8).reshape(
                (self.height, self.width, 3)
            )
            try:
                self._queue.put(frame, timeout=1.0)
            except queue.Full:
                pass  # drop frame to avoid deadlock

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def latest_frame(self, timeout: float, pace: bool = True) -> Optional["np.ndarray"]:
        if pace:
            interval = 1.0 / float(self.target_fps)
            with self._lock:
                now = time.perf_counter()
                if self._last_frame_time:
                    remaining = interval - (now - self._last_frame_time)
                    if remaining > 0:
                        time.sleep(remaining)
                self._last_frame_time = time.perf_counter()
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def diagnostics(self) -> str:
        details = []
        if self._proc:
            exit_code = self._proc.poll()
            if exit_code is not None:
                details.append(f"ffmpeg exit code {exit_code}")
        if self._ffmpeg_exit_code is not None and (
            not details or str(self._ffmpeg_exit_code) not in details[-1]
        ):
            details.append(f"ffmpeg exit code {self._ffmpeg_exit_code}")
        with self._stderr_lock:
            if self._stderr_lines:
                tail = list(self._stderr_lines)[-5:]
                details.append("ffmpeg stderr: " + " | ".join(tail))
        return "; ".join(details)

    def close(self) -> None:
        """Stop the stream and release resources."""
        ACTIVE_STREAMS.pop(self.stream_id, None)
        self._running.clear()
        if self._proc:
            self._kill_proc(self._proc)
        if self._thread.is_alive():
            self._thread.join(timeout=3.0)
        if self._refresher_thread and self._refresher_thread.is_alive():
            self._refresher_thread.join(timeout=2.0)

    def __repr__(self) -> str:
        return f"<StreamResource id={self.stream_id} url={self.hls_url} size={self.width}x{self.height}>"

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of this stream."""
        return {
            "_type": "StreamResource",
            "stream_id": self.stream_id,
            "width": self.width,
            "height": self.height,
            "target_fps": self.target_fps,
            "active": self._running.is_set(),
        }


FL511_RESOLVE_SPEC = NodeSpec(
    type="fl511.get_stream_url",
    version="1.0.0",
    display_name="Get FL511 Stream URL",
    category="FL511 Camera",
    summary="Get the HLS stream URL for a FL511 camera.",
    description="Uses a headless browser to resolve the stream URL and probe its resolution.",
    icon="camera",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="camera", type=t_int(), required=False, default=2130),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="camera", type=t_int()),
        PortSpec(name="url", type=t_string()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
)


@register_node(FL511_RESOLVE_SPEC)
class Fl511ResolveNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        camera_id = inputs.get("camera")
        camera_id = int(camera_id if camera_id is not None else 2130)
        ctx.log(f"Resolving FL511 stream for camera {camera_id}")
        hls_url = _resolve_fl511_hls_url(camera_id)
        width, height = _probe_stream_resolution(hls_url)
        ctx.log(f"Resolved stream {camera_id} at {width}x{height}")
        return {
            "control_out": None,
            "camera": camera_id,
            "url": hls_url,
            "width": width,
            "height": height,
        }


FL511_START_SPEC = NodeSpec(
    type="fl511.connect",
    version="1.0.0",
    display_name="Connect FL511 Stream",
    category="FL511 Camera",
    summary="Connect to a FL511 camera stream.",
    description="Starts a background reader and returns a stream object for fetching frames.",
    icon="camera",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="camera", type=t_int(), required=False, default=2130),
        PortSpec(name="url", type=t_string(), required=False, default=None),
        PortSpec(name="fps", type=t_int(), required=False, default=15),
        PortSpec(name="buffer_seconds", type=t_int(), required=False, default=4),
        PortSpec(name="refresh_minutes", type=t_int(), required=False, default=4),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="stream", type=t_stream()),
        PortSpec(name="stream_id", type=t_string()),
        PortSpec(name="url", type=t_string()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(FL511_START_SPEC)
class Fl511StartNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        hls_url = inputs.get("url")
        camera_id = inputs.get("camera")
        if camera_id is not None:
            camera_id = int(camera_id)
        else:
            camera_id = 2130
            
        if not hls_url:
            ctx.log(f"Resolving FL511 stream for camera {camera_id}")
            hls_url = _resolve_fl511_hls_url(camera_id)

        target_fps = int(inputs.get("fps") if inputs.get("fps") is not None else 15)
        buffer_seconds = int(inputs.get("buffer_seconds") if inputs.get("buffer_seconds") is not None else 4)
        refresh_minutes = int(inputs.get("refresh_minutes") if inputs.get("refresh_minutes") is not None else 4)

        stream_id = str(uuid.uuid4())[:8]
        stream = StreamResource(
            stream_id,
            str(hls_url),
            target_fps,
            buffer_seconds,
            camera_id=camera_id,
            refresh_minutes=refresh_minutes,
        )

        # Register the stream resource so it gets cleaned up automatically
        if hasattr(ctx, "register_resource"):
            ctx.register_resource(stream)

        ctx.log(f"Connected stream {stream_id} at {stream.width}x{stream.height}")
        return {
            "control_out": None,
            "stream": stream,
            "stream_id": stream_id,
            "url": str(hls_url),
            "width": stream.width,
            "height": stream.height,
        }


FL511_TICK_SPEC = NodeSpec(
    type="fl511.get_frame",
    version="1.0.0",
    display_name="Get FL511 Frame",
    category="FL511 Camera",
    summary="Get the next frame from a stream.",
    description="Reads the latest frame from a running stream and returns it as a JPEG data URL.",
    icon="camera",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="stream", type=t_stream(), required=True, default=None),
        PortSpec(name="timeout", type=t_float(), required=False, default=1.0),
        PortSpec(name="quality", type=t_int(), required=False, default=85),
        PortSpec(name="require_frame", type=t_boolean(), required=False, default=True),
        PortSpec(name="pace", type=t_boolean(), required=False, default=True),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="image", type=t_string().with_nullable(True), required=False, default=None),
        PortSpec(name="has_frame", type=t_boolean()),
        PortSpec(name="timestamp", type=t_float()),
        PortSpec(name="width", type=t_int()),
        PortSpec(name="height", type=t_int()),
    ],
    cache_policy="disabled",
)


@register_node(FL511_TICK_SPEC)
class Fl511TickNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        stream = inputs.get("stream")
        if not stream or not isinstance(stream, StreamResource):
            raise ValueError("Invalid or missing input: stream")
        
        timeout = float(inputs.get("timeout") if inputs.get("timeout") is not None else 1.0)
        jpeg_quality = int(inputs.get("quality") if inputs.get("quality") is not None else 85)
        require_frame = bool(inputs.get("require_frame") if inputs.get("require_frame") is not None else True)
        pace = bool(inputs.get("pace") if inputs.get("pace") is not None else True)

        frame = stream.latest_frame(timeout=timeout, pace=pace)
        if frame is None:
            if require_frame:
                diagnostics = stream.diagnostics()
                if diagnostics:
                    raise TimeoutError(f"No frame available within {timeout}s. {diagnostics}")
                raise TimeoutError(f"No frame available within {timeout}s")
            return {
                "control_out": None,
                "image": None,
                "has_frame": False,
                "timestamp": time.time(),
                "width": stream.width,
                "height": stream.height,
            }

        _require_cv2()
        ok, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if not ok:
            raise RuntimeError("Failed to encode frame")
        image_data = base64.b64encode(buffer).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{image_data}"
        # ctx.log(f"Fetched frame from stream {stream.stream_id}")
        return {
            "control_out": None,
            "image": image_url,
            "has_frame": True,
            "timestamp": time.time(),
            "width": stream.width,
            "height": stream.height,
        }


FL511_STOP_SPEC = NodeSpec(
    type="fl511.disconnect",
    version="1.0.0",
    display_name="Disconnect FL511 Stream",
    category="FL511 Camera",
    summary="Disconnect from a FL511 stream.",
    description="Stops the background stream reader and releases resources.",
    icon="camera",
    inputs=[
        PortSpec(name="control_in", type=t_control(), required=False, default=None),
        PortSpec(name="stream", type=t_stream(), required=True, default=None),
    ],
    outputs=[
        PortSpec(name="control_out", type=t_control(), required=False, default=None),
        PortSpec(name="stopped", type=t_boolean()),
    ],
    cache_policy="disabled",
)


@register_node(FL511_STOP_SPEC)
class Fl511StopNode(NodeBase):
    def forward(self, inputs: Dict[str, Any], ctx: ExecutionContext) -> Dict[str, Any]:
        stream = inputs.get("stream")
        if not stream or not isinstance(stream, StreamResource):
            raise ValueError("Invalid or missing input: stream")
            
        stream.close()
        ctx.log(f"Disconnected stream {stream.stream_id}")
        return {"control_out": None, "stopped": True}
