"""
Tests for ``app.domain.graph_migrations``.

Covers Phase 1's first registered migration step
(``"1.0" -> "1.1"``) which rewrites legacy ``{"kind": "string"}``
overrides on ``core.image.load.image`` (output) and
``core.image.save.image`` (input) to ``{"kind": "image"}``.
"""

from __future__ import annotations

import copy

from app.domain.graph_migrations import (
    CURRENT_SCHEMA_VERSION,
    MIGRATIONS,
    migrate,
)


class TestMigrationRegistry:
    """Sanity checks on the migration chain itself."""

    def test_current_version_is_1_1(self) -> None:
        # Phase 1 bumps the version. Phase 0's CURRENT was "1.0".
        assert CURRENT_SCHEMA_VERSION == "1.1"

    def test_migration_chain_is_linear(self) -> None:
        # No gaps, no branches. _build_chain raises if violated.
        from app.domain.graph_migrations import _build_chain
        chain = _build_chain()
        assert ("1.0" in chain), "1.0 -> 1.1 step must be registered"

    def test_chain_is_non_empty(self) -> None:
        assert len(MIGRATIONS) >= 1


class TestImagePortRewrite:
    """The 1.0 -> 1.1 transform itself."""

    def _make_legacy_graph(self) -> dict:
        """A synthetic 1.0 graph with t_string overrides on image ports."""
        return {
            "schema_version": "1.0",
            "nodes": [
                {
                    "id": "load-1",
                    "type": "core.image.load",
                    "input_values": {"file_path": "/tmp/sample.png"},
                    "output_port_types_override": {
                        # Legacy: image output advertised as plain string.
                        "image": {"kind": "string"},
                    },
                },
                {
                    "id": "save-1",
                    "type": "core.image.save",
                    "input_port_types_override": {
                        # Legacy: image input was nullable string.
                        "image": {"kind": "string", "nullable": True},
                    },
                },
            ],
            "links": [
                {
                    "from_node": "load-1",
                    "from_port": "image",
                    "to_node":   "save-1",
                    "to_port":   "image",
                },
            ],
        }

    def test_legacy_string_image_ports_rewrite_to_image(self) -> None:
        graph = self._make_legacy_graph()
        migrated = migrate(graph)

        # Schema version stamped forward.
        assert migrated["schema_version"] == "1.1"

        # Load output rewritten with subtype="data_url".
        load = next(n for n in migrated["nodes"] if n["id"] == "load-1")
        load_image_type = load["output_port_types_override"]["image"]
        assert load_image_type["kind"] == "image"
        assert load_image_type.get("metadata", {}).get("subtype") == "data_url"

        # Save input rewritten, nullable preserved.
        save = next(n for n in migrated["nodes"] if n["id"] == "save-1")
        save_image_type = save["input_port_types_override"]["image"]
        assert save_image_type["kind"] == "image"
        assert save_image_type.get("nullable") is True
        # Save input does NOT get a subtype tag.
        assert "subtype" not in save_image_type.get("metadata", {})

    def test_migration_does_not_mutate_input(self) -> None:
        graph = self._make_legacy_graph()
        snapshot = copy.deepcopy(graph)
        migrate(graph)
        assert graph == snapshot, "migrate() must not mutate caller's dict"

    def test_already_1_1_graph_passes_through(self) -> None:
        # A graph already at 1.1 with the new image type is left alone.
        graph = {
            "schema_version": "1.1",
            "nodes": [
                {
                    "id": "load-1",
                    "type": "core.image.load",
                    "output_port_types_override": {
                        "image": {
                            "kind": "image",
                            "metadata": {"subtype": "data_url"},
                        },
                    },
                },
            ],
            "links": [],
        }
        migrated = migrate(graph)
        assert migrated == graph

    def test_graph_without_overrides_is_unchanged_modulo_version(self) -> None:
        """Most graphs don't pin port-type overrides. They should pass
        through untouched except for the version stamp."""
        graph = {
            "schema_version": "1.0",
            "nodes": [
                {"id": "load-1", "type": "core.image.load"},
                {"id": "save-1", "type": "core.image.save"},
            ],
            "links": [
                {
                    "from_node": "load-1", "from_port": "image",
                    "to_node":   "save-1", "to_port":   "image",
                },
            ],
        }
        migrated = migrate(graph)
        assert migrated["schema_version"] == "1.1"
        assert migrated["nodes"] == graph["nodes"]
        assert migrated["links"] == graph["links"]

    def test_unrelated_string_overrides_left_alone(self) -> None:
        """Only image ports on core.image.load/save get rewritten —
        a string override on some other node's port is preserved."""
        graph = {
            "schema_version": "1.0",
            "nodes": [
                {
                    "id": "concat-1",
                    "type": "core.string.concat",
                    "output_port_types_override": {
                        "out": {"kind": "string"},
                    },
                },
            ],
            "links": [],
        }
        migrated = migrate(graph)
        assert (
            migrated["nodes"][0]["output_port_types_override"]["out"]
            == {"kind": "string"}
        )

    def test_graph_without_schema_version_treated_as_1_0(self) -> None:
        """A pre-Phase-0 graph dict (no version field) is still legal —
        treat it as 1.0 and run the chain."""
        graph = {
            "nodes": [
                {
                    "id": "load-1",
                    "type": "core.image.load",
                    "output_port_types_override": {
                        "image": {"kind": "string"},
                    },
                },
            ],
            "links": [],
        }
        migrated = migrate(graph)
        assert migrated["schema_version"] == "1.1"
        assert (
            migrated["nodes"][0]["output_port_types_override"]["image"]["kind"]
            == "image"
        )

    def test_idempotent_when_run_twice(self) -> None:
        graph = self._make_legacy_graph()
        once = migrate(graph)
        twice = migrate(once)
        assert once == twice
