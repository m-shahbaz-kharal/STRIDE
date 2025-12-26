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


def coerce_number(value: Any) -> Optional[float]:
    return _to_number(value)
