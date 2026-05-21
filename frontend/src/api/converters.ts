// Converter index — Phase 5 §4.7.
//
// The frontend fetches `/api/converters` once at app start and caches the
// resulting (from_kind, to_kind) -> ConverterSpec[] index. Connection
// validation then consults the index to decide whether an invalid edge
// can be repaired by inserting a single converter node.

import { authFetch } from "../api";

export interface ConverterSpec {
  node_type: string;
  display_name: string;
  from_kind: string;
  to_kind: string;
  cost: number;
  suggested: boolean;
  summary: string;
  category: string;
  icon: string;
  input_ports: string[];
  output_ports: string[];
}

export interface ConverterIndex {
  // Fast lookup by (from_kind, to_kind). Always returns a (possibly
  // empty) array — never undefined.
  lookup: (fromKind: string, toKind: string) => ConverterSpec[];
  // Cheapest converter for a (from, to) pair, or undefined if none.
  best: (fromKind: string, toKind: string) => ConverterSpec | undefined;
  // Every converter, in registration order, for diagnostics / debug.
  all: ConverterSpec[];
}

const EMPTY_INDEX: ConverterIndex = {
  lookup: () => [],
  best: () => undefined,
  all: [],
};

const buildIndex = (specs: ConverterSpec[]): ConverterIndex => {
  const map = new Map<string, ConverterSpec[]>();
  for (const spec of specs) {
    const key = `${spec.from_kind}->${spec.to_kind}`;
    const bucket = map.get(key);
    if (bucket) {
      bucket.push(spec);
    } else {
      map.set(key, [spec]);
    }
  }
  // Sort each bucket cheapest-first so `best()` is a constant-time
  // bucket[0] lookup.
  for (const bucket of map.values()) {
    bucket.sort((a, b) => a.cost - b.cost);
  }
  return {
    lookup: (fromKind: string, toKind: string) =>
      map.get(`${fromKind}->${toKind}`) ?? [],
    best: (fromKind: string, toKind: string) =>
      map.get(`${fromKind}->${toKind}`)?.[0],
    all: specs,
  };
};

export const fetchConverterIndex = async (): Promise<ConverterIndex> => {
  try {
    const response = await authFetch("/api/converters");
    if (!response.ok) {
      // Endpoint missing (e.g. older backend) or unauthenticated — return
      // an empty index so the editor degrades gracefully to "no
      // suggestions" rather than crashing.
      return EMPTY_INDEX;
    }
    const payload = (await response.json()) as { converters?: ConverterSpec[] };
    const specs = Array.isArray(payload.converters) ? payload.converters : [];
    return buildIndex(specs);
  } catch {
    return EMPTY_INDEX;
  }
};

export const buildConverterIndex = buildIndex;
export const emptyConverterIndex = (): ConverterIndex => EMPTY_INDEX;
