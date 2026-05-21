"""STRIDE plugin: traffic and transportation engineering nodes."""

# Importing the nodes module(s) triggers @register_node side effects.
from . import types as _types  # noqa: F401
from . import calibration as _calibration  # noqa: F401
from . import roi as _roi  # noqa: F401
from . import counting as _counting  # noqa: F401
from . import flow as _flow  # noqa: F401
from . import speed as _speed  # noqa: F401
from . import trajectory as _trajectory  # noqa: F401
from . import safety as _safety  # noqa: F401
from . import events as _events  # noqa: F401
from . import intersection as _intersection  # noqa: F401
from . import pedestrian as _pedestrian  # noqa: F401
from . import report as _report  # noqa: F401
from . import crash as _crash  # noqa: F401


def register() -> None:
    """Plugin entry point.

    Node registration happens at import time via @register_node.
    This function is the entry-point hook the plugin loader calls;
    the imports above are what actually exercise the decorators.
    """
    pass


__all__ = ["register"]
