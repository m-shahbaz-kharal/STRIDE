# stride-converters

The `convert.*` node family for STRIDE. These nodes wrap small, well-known
operations that bridge between the canonical types declared in
`stride-core` (image, bbox2d, detections2d, pointcloud, depthmap, …).

Every converter is referenced by the frontend's connection-validation
hook: when the user drags an edge from a port whose kind doesn't match
the target, the editor consults the converter index built from these
specs and offers a one-click "insert converter" action.

See `docs/architecture/unified-type-system-and-ux.md` §4.5.
