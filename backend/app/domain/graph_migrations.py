"""
Graph schema migrations.

Saved graphs carry a ``schema_version`` string. When a graph is loaded,
this module's :func:`migrate` walks the registered migration chain to
bring the graph forward to :data:`CURRENT_SCHEMA_VERSION`.

Migrations are pure JSON transforms — they never instantiate nodes or
inspect runtime state. Adding a new migration means:

1. Bump :data:`CURRENT_SCHEMA_VERSION` (semver, single digit increments
   are fine for now).
2. Implement a ``_migrate_<from>_to_<to>(graph) -> graph`` function.
3. Append ``(from, to, fn)`` to :data:`MIGRATIONS`.

The chain is validated at module load via :func:`_build_chain` —
duplicate sources or gaps raise immediately.

Backward compatibility
----------------------
Graphs without a ``schema_version`` field are treated as ``"1.0"``.
:func:`migrate` is **idempotent and total** — every legal graph passes
through unchanged when there are no applicable migrations.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Tuple


CURRENT_SCHEMA_VERSION: str = "1.1"
"""The schema version that newly-saved graphs are tagged with."""


# A migration takes a graph dict at version ``from_version`` and returns the
# graph dict at the next version. Migrations are pure and total — they must
# never raise on a legal graph at the source version.
MigrationFn = Callable[[dict], dict]


# =============================================================================
# 1.0 -> 1.1: image port type rewrite
# =============================================================================
#
# In schema 1.0, ``core.image.load.image`` (output) and
# ``core.image.save.image`` (input) advertised type ``{"kind": "string"}``
# because the wire payload happens to be a base64 data URL. In 1.1 they
# advertise ``{"kind": "image"}`` (with ``subtype="data_url"`` on the
# output) so the cross-package wiring with image consumers (yolo,
# clip, depth-anything, …) actually type-checks.
#
# Saved graphs may carry per-node ``input_port_types_override`` /
# ``output_port_types_override`` dicts that pinned the old string type.
# This migration rewrites those overrides to the new image type so a
# 1.0 graph loads cleanly.
#
# (Graphs that did NOT pin overrides need no rewrite — port types are
# resolved from each node's spec at build time. The migration is still
# pure: a graph without overrides passes through untouched.)


_IMAGE_PORT_REWRITES: Dict[str, Dict[str, Tuple[str, ...]]] = {
    # node_type -> direction -> tuple of port names that switched
    "core.image.load": {"output": ("image",)},
    "core.image.save": {"input": ("image",)},
}


def _rewrite_string_to_image(port_type: Any, *, subtype: str | None = None) -> Any:
    """Return a port-type literal rewritten from ``string`` to ``image``.

    Pure on the input. Returns the input unchanged when it is not a
    plain ``{"kind": "string"}`` literal — this protects against
    double-application and against graphs that already carry a richer
    type than the legacy string.
    """
    if not isinstance(port_type, dict):
        return port_type
    if port_type.get("kind") != "string":
        return port_type
    new_type: Dict[str, Any] = {"kind": "image"}
    # Preserve nullable flag (e.g. core.image.save's input is nullable).
    if port_type.get("nullable"):
        new_type["nullable"] = True
    if subtype:
        new_type["metadata"] = {"subtype": subtype}
    return new_type


def _migrate_1_0_to_1_1(graph: dict) -> dict:
    """Rewrite legacy ``string`` image-port-type overrides to ``image``.

    Only touches ``input_port_types_override`` / ``output_port_types_override``
    entries on nodes whose ``type`` is one of ``core.image.load`` or
    ``core.image.save``, and only for the specific ports that changed
    (output ``image`` on load, input ``image`` on save).
    """
    nodes = graph.get("nodes")
    if not isinstance(nodes, list):
        return graph

    out_nodes: List[Any] = []
    for node in nodes:
        if not isinstance(node, dict):
            out_nodes.append(node)
            continue
        node_type = node.get("type")
        rewrites = _IMAGE_PORT_REWRITES.get(str(node_type)) if node_type else None
        if not rewrites:
            out_nodes.append(node)
            continue

        new_node = dict(node)
        for direction, port_names in rewrites.items():
            override_key = (
                "input_port_types_override"
                if direction == "input"
                else "output_port_types_override"
            )
            overrides = new_node.get(override_key)
            if not isinstance(overrides, dict):
                continue
            new_overrides = dict(overrides)
            changed = False
            for port_name in port_names:
                if port_name not in new_overrides:
                    continue
                # core.image.load output gets subtype="data_url"; the
                # save input is consumed and just needs `image`.
                subtype = "data_url" if (
                    node_type == "core.image.load" and direction == "output"
                ) else None
                rewritten = _rewrite_string_to_image(
                    new_overrides[port_name], subtype=subtype,
                )
                if rewritten is not new_overrides[port_name]:
                    new_overrides[port_name] = rewritten
                    changed = True
            if changed:
                new_node[override_key] = new_overrides
        out_nodes.append(new_node)

    out = dict(graph)
    out["nodes"] = out_nodes
    return out


# Ordered list of (from_version, to_version, fn) tuples. Ordering by source
# version is enforced lexically: each entry's ``from_version`` must equal the
# previous entry's ``to_version``. Add new migrations at the end.
MIGRATIONS: List[Tuple[str, str, MigrationFn]] = [
    ("1.0", "1.1", _migrate_1_0_to_1_1),
]


def _build_chain() -> Dict[str, Tuple[str, MigrationFn]]:
    """Index migrations by source version for O(1) chain walking.

    Validates that the chain is well-formed: each migration's source version
    is unique (no branching) and equals the previous migration's target
    version (no gaps).
    """
    chain: Dict[str, Tuple[str, MigrationFn]] = {}
    prev_to: str | None = None
    for from_v, to_v, fn in MIGRATIONS:
        if from_v in chain:
            raise RuntimeError(
                f"graph_migrations: duplicate source version {from_v!r} in "
                f"MIGRATIONS — chain must be linear"
            )
        if prev_to is not None and from_v != prev_to:
            raise RuntimeError(
                f"graph_migrations: gap in chain — previous migration "
                f"targets {prev_to!r} but next starts at {from_v!r}"
            )
        chain[from_v] = (to_v, fn)
        prev_to = to_v
    return chain


# Build the chain once at module import time. ``migrate`` is called
# per-graph on every list/load request, so re-running the validation
# loop each call adds measurable overhead for large libraries.
_MIGRATION_CHAIN: Dict[str, Tuple[str, MigrationFn]] = _build_chain()


def migrate(graph: dict) -> dict:
    """Walk the migration chain to bring ``graph`` to the current version.

    Pure pass-through when ``graph['schema_version']`` is already current.
    Graphs without a ``schema_version`` field are treated as ``"1.0"``.

    The returned graph always has ``schema_version`` set to
    :data:`CURRENT_SCHEMA_VERSION`. The original graph is not mutated; this
    function is safe to call on shared/immutable input.
    """
    if not isinstance(graph, dict):
        # Be defensive — graph storage in the DB is a JSONB column, so it can
        # technically be any JSON value. Only dicts are migratable.
        return graph

    # Defensive copy — never mutate caller's dict.
    out = dict(graph)
    raw_version = out.get("schema_version")
    version = raw_version or "1.0"

    chain = _MIGRATION_CHAIN
    seen: set[str] = set()
    while version != CURRENT_SCHEMA_VERSION:
        if version in seen:
            raise RuntimeError(
                f"graph_migrations: cycle detected at version {version!r}"
            )
        seen.add(version)
        step = chain.get(version)
        if step is None:
            # No migration registered from this version — either the graph is
            # newer than us (don't downgrade its tag) or the chain has a hole
            # we can't bridge. Leave the version field alone.
            break
        to_v, fn = step
        out = fn(out)
        version = to_v

    if version == CURRENT_SCHEMA_VERSION:
        # Either we walked the chain to the current version, or the graph
        # was already current, or no version was set at all. Stamp it.
        out["schema_version"] = CURRENT_SCHEMA_VERSION
    # Else: future-version graph we couldn't migrate — leave its tag intact.
    return out


__all__ = [
    "CURRENT_SCHEMA_VERSION",
    "MIGRATIONS",
    "migrate",
]
