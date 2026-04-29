// Phase 3 §7.2 — Tiny in-house fuzzy matcher for the NodeSearchPalette.
//
// We deliberately do NOT pull in fuse.js / fzf — the user has been
// explicit about not adding heavy deps. The algorithm here is the
// classic "subsequence + bonus" used by Sublime/VSCode-style command
// palettes:
//
//   1. The query characters must appear in order in the candidate
//      (case-insensitive). Non-subsequence ⇒ score 0 (no match).
//   2. Among candidates that match, the score rewards:
//        - Exact match
//        - Prefix match
//        - Word-boundary starts ("io" matches "ImageOverlay" well)
//        - Compactness (consecutive matched chars)
//
// The score is a positive number; higher = better. Score 0 means the
// candidate does not match the query.

export interface FuzzyMatchResult {
  score: number;
  // Indices of matched characters in the candidate (for highlight).
  positions: number[];
}

const NO_MATCH: FuzzyMatchResult = { score: 0, positions: [] };

const isWordBoundary = (text: string, idx: number): boolean => {
  if (idx === 0) return true;
  const prev = text[idx - 1];
  // After whitespace, separators, or a lower→upper transition.
  return (
    prev === " " ||
    prev === "_" ||
    prev === "-" ||
    prev === "." ||
    prev === "/" ||
    (prev === prev.toLowerCase() && text[idx] === text[idx].toUpperCase() && /[A-Z]/.test(text[idx]))
  );
};

export const fuzzyMatch = (query: string, candidate: string): FuzzyMatchResult => {
  if (!query) return { score: 1, positions: [] };
  if (!candidate) return NO_MATCH;

  const q = query.toLowerCase();
  const c = candidate.toLowerCase();

  // Length penalty (small): if two candidates tie on the rule-based
  // score, the shorter one ranks higher. Capped so long names that
  // match well still win over short noise.
  const lengthPenalty = Math.min(c.length, 50);

  // Fast path — exact / prefix.
  if (q === c) return { score: 1000, positions: Array.from({ length: c.length }, (_, i) => i) };
  if (c.startsWith(q)) {
    return { score: 900 - lengthPenalty * 0.5, positions: Array.from({ length: q.length }, (_, i) => i) };
  }
  if (c.includes(q)) {
    const start = c.indexOf(q);
    const positions = Array.from({ length: q.length }, (_, i) => start + i);
    // Prefer matches that start at a word boundary.
    const boundaryBonus = isWordBoundary(candidate, start) ? 200 : 0;
    return { score: 700 + boundaryBonus - lengthPenalty * 0.5, positions };
  }

  // Subsequence walk.
  const positions: number[] = [];
  let qi = 0;
  let score = 0;
  let consecutive = 0;
  for (let ci = 0; ci < c.length && qi < q.length; ci++) {
    if (c[ci] === q[qi]) {
      positions.push(ci);
      let charScore = 10;
      if (isWordBoundary(candidate, ci)) charScore += 30;
      if (consecutive > 0) charScore += 5 * consecutive;
      score += charScore;
      consecutive += 1;
      qi += 1;
    } else {
      consecutive = 0;
    }
  }

  if (qi < q.length) return NO_MATCH;
  return { score, positions };
};

// Convenience: rank a list of candidates against a query, drop misses,
// sort by score desc with stable tiebreak by candidate index.
export const fuzzyRank = <T,>(
  query: string,
  items: T[],
  toString: (item: T) => string
): Array<{ item: T; score: number; positions: number[] }> => {
  if (!query) return items.map((item) => ({ item, score: 1, positions: [] }));
  const out: Array<{ item: T; score: number; positions: number[]; index: number }> = [];
  for (let i = 0; i < items.length; i++) {
    const m = fuzzyMatch(query, toString(items[i]));
    if (m.score > 0) {
      out.push({ item: items[i], score: m.score, positions: m.positions, index: i });
    }
  }
  out.sort((a, b) => (b.score - a.score) || (a.index - b.index));
  return out.map(({ item, score, positions }) => ({ item, score, positions }));
};
