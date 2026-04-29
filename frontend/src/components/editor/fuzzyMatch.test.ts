// Phase 3 §7.2 — NodeSearchPalette fuzzy matcher tests.

import { describe, expect, it } from "vitest";
import { fuzzyMatch, fuzzyRank } from "./fuzzyMatch";

describe("fuzzyMatch", () => {
  it("returns a high score for an exact match", () => {
    const r = fuzzyMatch("yolo", "yolo");
    expect(r.score).toBe(1000);
  });

  it("returns a high score for a prefix match", () => {
    const r = fuzzyMatch("yo", "YOLO Detector");
    // Prefix base 900 minus a small length penalty — anchor at 850 so
    // the test stays correct when we tune the length-bias coefficient.
    expect(r.score).toBeGreaterThanOrEqual(850);
  });

  it("returns a positive score for a substring match", () => {
    const r = fuzzyMatch("detector", "Yolo Detector");
    expect(r.score).toBeGreaterThan(0);
  });

  it("returns a positive score for a subsequence match", () => {
    const r = fuzzyMatch("ydt", "Yolo Detector");
    expect(r.score).toBeGreaterThan(0);
  });

  it("returns 0 score for non-matches", () => {
    expect(fuzzyMatch("xxx", "yolo detector").score).toBe(0);
  });

  it("rewards word-boundary matches", () => {
    // Both candidates require subsequence matching ("im" appears as a
    // substring nowhere). The word-boundary one ("Image Manipulation")
    // should score higher than the buried one ("zimimaginate").
    const a = fuzzyMatch("im", "Image Manipulation");      // i + m at word starts
    const b = fuzzyMatch("im", "zimimaginate");            // mid-word
    expect(a.score).toBeGreaterThan(b.score);
  });

  it("returns matched positions for highlighting", () => {
    const r = fuzzyMatch("io", "image overlay");
    expect(r.positions.length).toBe(2);
    expect(r.positions[0]).toBe(0);     // i
    // Subsequent 'o' should match within the candidate.
    expect(r.positions[1]).toBeGreaterThan(0);
  });

  it("treats empty query as a free pass", () => {
    expect(fuzzyMatch("", "anything").score).toBeGreaterThan(0);
  });
});

describe("fuzzyRank", () => {
  const items = ["YOLO Detector", "Hello World", "Yarn Online", "Detector"];

  it("filters out non-matches", () => {
    const out = fuzzyRank("yolo", items, (s) => s);
    expect(out.map((r) => r.item)).toContain("YOLO Detector");
    expect(out.map((r) => r.item)).not.toContain("Hello World");
  });

  it("ranks better matches first", () => {
    const out = fuzzyRank("det", items, (s) => s);
    // Both "YOLO Detector" and "Detector" should rank, with the
    // exact-prefix one ("Detector") scoring at least as high.
    const detIdx = out.findIndex((r) => r.item === "Detector");
    const yoloDetIdx = out.findIndex((r) => r.item === "YOLO Detector");
    expect(detIdx).toBeGreaterThanOrEqual(0);
    expect(yoloDetIdx).toBeGreaterThanOrEqual(0);
    expect(detIdx).toBeLessThanOrEqual(yoloDetIdx);
  });

  it("returns empty array when nothing matches", () => {
    expect(fuzzyRank("zzz", items, (s) => s)).toHaveLength(0);
  });

  it("returns all items for empty query", () => {
    expect(fuzzyRank("", items, (s) => s)).toHaveLength(items.length);
  });
});
