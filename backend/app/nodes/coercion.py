from __future__ import annotations

from typing import Any, Optional, Tuple


def _to_number(value: Any) -> Optional[float]:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def coerce_add(a: Any, b: Any) -> Tuple[Any, str]:
    """Coerce for add: strings concatenate, numbers add, otherwise fallback."""
    if isinstance(a, str) or isinstance(b, str):
        return f"{'' if a is None else a}{'' if b is None else b}", "string"
    num_a = _to_number(a)
    num_b = _to_number(b)
    if num_a is None or num_b is None:
        return 0.0, "number"
    return num_a + num_b, "number"


def coerce_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce a value to a float, returning default if it fails."""
    num = _to_number(value)
    return float(num) if num is not None else default


def coerce_int(value: Any, default: int = 0) -> int:
    """Safely coerce a value to an integer, returning default if it fails."""
    num = _to_number(value)
    return int(num) if num is not None else default


def coerce_bool(value: Any, default: bool = False) -> bool:
    """Safely coerce a value to a boolean, handling string "false" / "0" correctly."""
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        val_str = value.strip().lower()
        if val_str in ("false", "0", "no", "f"):
            return False
        return True
    return bool(value)


def coerce_number(value: Any) -> Optional[float]:
    return _to_number(value)
