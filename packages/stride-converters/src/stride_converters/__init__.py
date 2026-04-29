"""STRIDE plugin: the ``convert.*`` node family.

This package houses every type-conversion node — the bridge layer between
the canonical record types declared in ``stride-core`` (image, bbox2d,
detections2d, pointcloud, depthmap, …).

The frontend builds a converter index from these specs at startup; when
a drag attempts an invalid connection but a registered converter goes
``source.kind -> target.kind``, the editor offers a one-click insert.

See ``docs/architecture/unified-type-system-and-ux.md`` §4.5.
"""

from .nodes import register

__all__ = ["register"]
