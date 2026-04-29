// Phase 3 §7.1 — classification API unit tests.
//
// These tests cover the *pure* classifier (`classifyAssignmentPure`)
// because the hook variant requires a React tree. Pure variant takes
// the same `arePortTypesCompatible` predicate the hook uses, so the
// behaviour is identical end-to-end.

import { describe, expect, it } from "vitest";

import { classifyAssignmentPure } from "./useConnectionValidation";
import type { TypeDescriptor } from "../types";

// Inline copy of the hook's `arePortTypesCompatible` so tests don't
// depend on React. Kept tiny — see useConnectionValidation.ts:67-105
// for the canonical version.
const isAssignable = (
  src: TypeDescriptor | string | undefined,
  tgt: TypeDescriptor | string | undefined
): boolean => {
  const norm = (t?: TypeDescriptor | string): TypeDescriptor =>
    !t ? { kind: "any" } : typeof t === "string" ? { kind: t as TypeDescriptor["kind"] } : t;
  const s = norm(src);
  const d = norm(tgt);
  if (d.kind === "any" || s.kind === "any") return true;
  if (s.kind === "int" && d.kind === "float") return true;
  if (s.kind !== d.kind) return false;
  // Subtype must match when target requires one.
  const sSub = (s.metadata?.subtype as string | undefined) ?? null;
  const dSub = (d.metadata?.subtype as string | undefined) ?? null;
  if (dSub && sSub !== dSub) return false;
  return true;
};

const t = (kind: TypeDescriptor["kind"], subtype?: string): TypeDescriptor =>
  subtype ? { kind, metadata: { subtype } } : { kind };

describe("classifyAssignmentPure", () => {
  it("returns 'compatible' for identical kinds", () => {
    expect(classifyAssignmentPure(t("image"), t("image"), isAssignable))
      .toBe("compatible");
  });

  it("returns 'compatible' when target is `any`", () => {
    expect(classifyAssignmentPure(t("image"), t("any"), isAssignable))
      .toBe("compatible");
  });

  it("returns 'compatible' for matching subtypes", () => {
    expect(
      classifyAssignmentPure(t("image", "rgb"), t("image", "rgb"), isAssignable)
    ).toBe("compatible");
  });

  it("returns 'compatible' for int → float widening", () => {
    expect(classifyAssignmentPure(t("int"), t("float"), isAssignable))
      .toBe("compatible");
  });

  it("returns 'convertible' when source has no subtype but target requires one", () => {
    // image[any] → image[rgb] : same kind, narrower subtype.
    expect(
      classifyAssignmentPure(t("image"), t("image", "rgb"), isAssignable)
    ).toBe("convertible");
  });

  it("returns 'convertible' for mismatched subtypes within the same kind", () => {
    expect(
      classifyAssignmentPure(t("image", "rgb"), t("image", "bgr"), isAssignable)
    ).toBe("convertible");
  });

  it("returns 'incompatible' for cross-kind pairs (no converter index yet)", () => {
    expect(classifyAssignmentPure(t("image"), t("pointcloud"), isAssignable))
      .toBe("incompatible");
  });

  it("returns 'incompatible' for unrelated scalars", () => {
    expect(classifyAssignmentPure(t("string"), t("boolean"), isAssignable))
      .toBe("incompatible");
  });

  it("treats undefined inputs as compatible (fall back to `any`)", () => {
    expect(classifyAssignmentPure(undefined, undefined, isAssignable))
      .toBe("compatible");
  });
});
