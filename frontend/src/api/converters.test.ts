// Phase 5 §4.7 — converter-index unit tests.

import { describe, expect, it } from "vitest";

import { buildConverterIndex, ConverterSpec } from "./converters";

const make = (
    nodeType: string,
    fromKind: string,
    toKind: string,
    cost = 3,
): ConverterSpec => ({
    node_type: nodeType,
    display_name: nodeType,
    from_kind: fromKind,
    to_kind: toKind,
    cost,
    suggested: true,
    summary: "",
    category: "Convert",
    icon: "",
    input_ports: ["control_in", "input"],
    output_ports: ["control_out", "output"],
});

describe("converter index", () => {
    it("returns empty arrays for unknown pairs", () => {
        const index = buildConverterIndex([]);
        expect(index.lookup("image", "pointcloud")).toEqual([]);
        expect(index.best("image", "pointcloud")).toBeUndefined();
    });

    it("indexes converters by (from, to) pair", () => {
        const index = buildConverterIndex([
            make("convert.image.from_url", "string", "image", 4),
            make("convert.depth.to_pointcloud", "depthmap", "pointcloud", 5),
        ]);
        expect(index.lookup("string", "image").map((c) => c.node_type)).toEqual([
            "convert.image.from_url",
        ]);
        expect(index.best("depthmap", "pointcloud")?.node_type).toBe(
            "convert.depth.to_pointcloud",
        );
    });

    it("sorts duplicates cheapest-first via best()", () => {
        const index = buildConverterIndex([
            make("convert.expensive", "string", "image", 9),
            make("convert.cheap", "string", "image", 2),
            make("convert.medium", "string", "image", 5),
        ]);
        expect(index.best("string", "image")?.node_type).toBe("convert.cheap");
        const all = index.lookup("string", "image");
        expect(all.map((c) => c.cost)).toEqual([2, 5, 9]);
    });

    it("preserves the registration order of `all` for diagnostics", () => {
        const specs = [
            make("convert.a", "string", "image", 1),
            make("convert.b", "string", "image", 1),
        ];
        const index = buildConverterIndex(specs);
        expect(index.all.map((c) => c.node_type)).toEqual(["convert.a", "convert.b"]);
    });
});
