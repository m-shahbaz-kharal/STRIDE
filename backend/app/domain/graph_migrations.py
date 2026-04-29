"""
Graph schema migrations.

Saved graphs carry a ``schema_version`` string. When a graph is loaded, this
module's :func:`migrate` walks the registered migration chain to bring the
graph forward to :data:`CURRENT_SCHEMA_VERSION`.

Phase 0 note
------------
This file is **scaffolding only**. The migration list is intentionally empty
— Phase 1 will add the first 1.0 → 1.1 step that rewrites legacy port type
literals (see ``docs/architecture/unified-type-system-and-ux.md`` §3.7).
The plumbing is permanent: future phases register entries in
:data:`MIGRATIONS` and :func:`migrate` walks them in order.

Backward compatibility
----------------------
Graphs without a ``schema_version`` field are treated as ``"1.0"``.
:func:`migrate` is **idempotent and total** — every legal graph passes
through unchanged when there are no applicable migrations.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple


CURRENT_SCHEMA_VERSION: str = "1.0"
"""The schema version that newly-saved graphs are tagged with."""


# A migration takes a graph dict at version ``from_version`` and returns the
# graph dict at the next version. Migrations are pure and total — they must
# never raise on a legal graph at the source version.
MigrationFn = Callable[[dict], dict]


# Ordered list of (from_version, to_version, fn) tuples. Ordering by source
# version is enforced lexically: each entry's ``from_version`` must equal the
# previous entry's ``to_version``. Add new migrations at the end.
MIGRATIONS: List[Tuple[str, str, MigrationFn]] = [
    # Phase 1 will add the first entry, e.g.:
    # ("1.0", "1.1", _migrate_1_0_to_1_1),
]


def _build_chain() -> Dict[str, Tuple[str, MigrationFn]]:
    """Index migrations by source version for O(1) chain walking.

    Validates that the chain is well-formed: each migration's source version
    is unique (no branching) and equals the previous migration's target
    version (no gaps). Phase 0 has zero entries so this is a no-op, but the
    invariant matters once Phase 1 lands.
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


def migrate(graph: dict) -> dict:
    """Walk the migration chain to bring ``graph`` to the current version.

    Pure pass-through when ``graph['schema_version']`` is already current
    (the Phase 0 default). Graphs without a ``schema_version`` field are
    treated as ``"1.0"``.

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

    chain = _build_chain()
    seen: set[str] = set()
    while version != CURRENT_SCHEMA_VERSION:
        if version in seen:
            raise RuntimeError(
                f"graph_migrations: cycle detected at version {version!r}"
            )
        seen.add(version)
        step = chain.get(version)
        if step is None:
            # No migration registered from this version. Phase 0 reaches this
            # branch only if a future graph carries a version newer than us
            # (e.g. ``2.5`` against current ``1.0``). Leave the version field
            # alone — we must never downgrade a future graph's tag.
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
