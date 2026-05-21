"""
Shared image utility helpers used by image-pipeline node packages.

Images flow through STRIDE as base64 strings (often as a data URL like
"data:image/jpeg;base64,..." produced by `core.image.load`).  These helpers
isolate the encoding details so individual nodes don't all reimplement
them.

These helpers intentionally have no hard numpy/cv2 dependency at import
time — they only use them inside functions that need them.  Callers must
guard against missing deps themselves.
"""

from __future__ import annotations

import base64
from io import BytesIO
from typing import Any, Optional, Tuple


def strip_data_url(image_str: Any) -> str:
    """Strip a `data:...;base64,` prefix and return raw base64.

    Accepts either:

    * a bare string (data URL or raw base64) — the convention used by
      ``core.image.load.image``;
    * a canonical Image record dict (``{"_type": "Image", ..., "data_b64":
      "..."}``) — the convention used by ``convert.image.from_url`` and
      anything that produces a structured Image.

    Returns ``""`` for anything else so callers can detect "missing" input.
    """
    if isinstance(image_str, dict):
        # Canonical Image record — pull data_b64.
        inner = image_str.get("data_b64")
        if not isinstance(inner, str):
            return ""
        image_str = inner
    if not isinstance(image_str, str):
        return ""
    if image_str.startswith("data:") and "," in image_str:
        return image_str.split(",", 1)[1]
    return image_str


def decode_image_bytes(image_str: Any) -> bytes:
    """Decode a STRIDE image string (or record) into raw bytes."""
    return base64.b64decode(strip_data_url(image_str))


def decode_image_to_numpy(image_str: Any) -> "Any":
    """Decode a STRIDE image (string or record) to an HxWxC BGR ndarray.

    Raises RuntimeError if numpy/opencv aren't available.
    """
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "decode_image_to_numpy requires numpy and opencv-python. "
            "Install with: pip install numpy opencv-python"
        ) from exc

    raw = decode_image_bytes(image_str)
    if not raw:
        raise ValueError("empty image data")
    arr = np.frombuffer(raw, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("failed to decode image bytes")
    return img


def encode_numpy_to_image(img: "Any", fmt: str = "jpeg", quality: int = 90) -> str:
    """Encode a HxWxC BGR numpy array as a data-URL base64 string."""
    try:
        import cv2  # type: ignore
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "encode_numpy_to_image requires opencv-python."
        ) from exc

    fmt = fmt.lower()
    ext = ".jpg" if fmt in ("jpg", "jpeg") else f".{fmt}"
    mime = "image/jpeg" if fmt in ("jpg", "jpeg") else f"image/{fmt}"
    params = []
    if fmt in ("jpg", "jpeg"):
        params = [int(__import__("cv2").IMWRITE_JPEG_QUALITY), int(quality)]
    elif fmt == "png":
        params = [int(__import__("cv2").IMWRITE_PNG_COMPRESSION), 3]
    ok, buf = cv2.imencode(ext, img, params)
    if not ok:
        raise RuntimeError("cv2.imencode failed")
    b64 = base64.b64encode(buf.tobytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def get_image_dimensions(image_str: str) -> Tuple[int, int]:
    """Return (width, height) of an encoded image string."""
    img = decode_image_to_numpy(image_str)
    h, w = img.shape[:2]
    return int(w), int(h)


def make_bbox2d(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    confidence: float,
    class_id: int,
    class_name: str,
    track_id: Optional[int] = None,
    extras: Optional[dict] = None,
) -> dict:
    """Build a bbox2d record (matches `t_bbox2d` schema)."""
    out = {
        "x1": float(x1),
        "y1": float(y1),
        "x2": float(x2),
        "y2": float(y2),
        "confidence": float(confidence),
        "class_id": int(class_id),
        "class_name": str(class_name),
    }
    if track_id is not None:
        out["track_id"] = int(track_id)
    if extras:
        out.update(extras)
    return out


def make_detections2d(
    boxes: list,
    width: int,
    height: int,
    image: Optional[str] = None,
) -> dict:
    """Build a detections2d record (matches t_detections2d convention).

    The ``image`` field is declared ``nullable=True`` on the canonical
    schema; absent values must be ``None``, not ``""``. The previous
    empty-string sentinel caused downstream nodes that try to decode the
    image to either silently produce garbage or raise ``"failed to
    decode image bytes"`` on what should have been a no-op.
    """
    return {
        "_type": "Detections2D",
        "image_width": int(width),
        "image_height": int(height),
        "boxes": list(boxes),
        "image": image if image else None,
    }
