import React, { useEffect, useMemo, useRef, useState } from "react";

import { NodeTypeDefinition, TypeDescriptor } from "../../types";
import { getCategoryColor } from "../../graph/utils";
import { fuzzyRank } from "./fuzzyMatch";

// Phase 3 §7.2 — `<NodeSearchPalette>` is the canonical way to add a
// node to the canvas. It replaces the old SmartConnectModal and is
// triggered by either:
//
//   • Ctrl+K / Cmd+K anywhere in the editor (no source — pure search)
//   • Drop-on-canvas while dragging from a port (pre-filtered to
//     compatible target types)
//
// Selecting a node creates it at the supplied flow position and (when
// invoked from a drag) auto-wires the source port to the first
// compatible input.

export interface PaletteSource {
  nodeId: string;
  handleId: string;
  type: "source" | "target";
  portType?: TypeDescriptor;
}

export interface NodeSearchPaletteProps {
  isOpen: boolean;
  // Screen-space anchor point for the palette popup.
  position: { x: number; y: number };
  onClose: () => void;
  onSelect: (nodeType: NodeTypeDefinition) => void;
  nodeTypes: NodeTypeDefinition[];
  // When non-null, the palette is in "drop-on-canvas" mode and shows
  // only nodes that have a compatible counterpart port.
  source: PaletteSource | null;
}

interface ScoredNode {
  node: NodeTypeDefinition;
  score: number;
  positions: number[];
  matchedField: "display_name" | "node_type" | "tag" | "category";
}

const HighlightedText: React.FC<{ text: string; positions: number[] }> = ({
  text,
  positions,
}) => {
  if (!positions || positions.length === 0) return <>{text}</>;
  const set = new Set(positions);
  return (
    <>
      {Array.from(text).map((ch, i) =>
        set.has(i) ? (
          <mark key={i} className="search-highlight">
            {ch}
          </mark>
        ) : (
          <React.Fragment key={i}>{ch}</React.Fragment>
        )
      )}
    </>
  );
};

const CATEGORY_ICONS: Record<string, string> = {
  Math: "+",
  Logic: "&",
  Strings: '"',
  Variables: "$",
  Control: ">",
  Literal: "#",
  Containers: "[]",
  Utility: "*",
};

const getCategoryIcon = (category: string): string =>
  CATEGORY_ICONS[category] ?? "?";

const NodeSearchPalette: React.FC<NodeSearchPaletteProps> = ({
  isOpen,
  position,
  onClose,
  onSelect,
  nodeTypes,
  source,
}) => {
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const modalRef = useRef<HTMLDivElement>(null);
  const lastInteractionRef = useRef<"mouse" | "keyboard" | null>(null);

  // Compute the ranked list. We rank against display_name, node_type,
  // category and any tags — keep the *best* hit per node.
  const ranked: ScoredNode[] = useMemo(() => {
    const trimmed = query.trim();

    // For each node, find its best match across fields and the matched
    // field name (for indicator badges).
    const scored: ScoredNode[] = [];
    for (const node of nodeTypes) {
      const tags = node.tags ?? [];
      const candidates: Array<{ field: ScoredNode["matchedField"]; text: string; weight: number }> = [
        { field: "display_name", text: node.display_name, weight: 1.0 },
        { field: "node_type", text: node.node_type, weight: 0.85 },
        { field: "category", text: node.category ?? "", weight: 0.6 },
        ...tags.map((tag) => ({ field: "tag" as const, text: tag, weight: 0.7 })),
      ];

      let best: ScoredNode | null = null;
      for (const cand of candidates) {
        if (!cand.text) continue;
        const ranked = fuzzyRank(trimmed, [cand.text], (s) => s);
        const top = ranked[0];
        if (!top) continue;
        const weighted = top.score * cand.weight;
        if (!best || weighted > best.score) {
          best = {
            node,
            score: weighted,
            positions: cand.field === "display_name" ? top.positions : [],
            matchedField: cand.field,
          };
        }
      }
      if (best) scored.push(best);
    }

    scored.sort((a, b) => {
      if (b.score !== a.score) return b.score - a.score;
      return a.node.display_name.localeCompare(b.node.display_name);
    });
    return scored;
  }, [nodeTypes, query]);

  // Reset selection when the result list changes.
  useEffect(() => {
    setSelectedIndex(0);
  }, [query, ranked.length]);

  // Auto-focus when opened.
  useEffect(() => {
    if (!isOpen) return;
    setQuery("");
    setSelectedIndex(0);
    const t = setTimeout(() => inputRef.current?.focus(), 30);
    return () => clearTimeout(t);
  }, [isOpen]);

  // Keyboard navigation (arrow keys, Enter, Esc).
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        lastInteractionRef.current = "keyboard";
        setSelectedIndex((prev) => Math.min(prev + 1, ranked.length - 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        lastInteractionRef.current = "keyboard";
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const pick = ranked[selectedIndex];
        if (pick) onSelect(pick.node);
      } else if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [isOpen, ranked, selectedIndex, onSelect, onClose]);

  // Click-outside dismiss.
  useEffect(() => {
    if (!isOpen) return;
    const handler = (e: MouseEvent | TouchEvent) => {
      const target = e.target as Node | null;
      if (modalRef.current && target instanceof Node && !modalRef.current.contains(target)) {
        onClose();
      }
    };
    document.addEventListener("mousedown", handler);
    document.addEventListener("touchstart", handler);
    return () => {
      document.removeEventListener("mousedown", handler);
      document.removeEventListener("touchstart", handler);
    };
  }, [isOpen, onClose]);

  // Scroll selected item into view (keyboard nav only).
  useEffect(() => {
    if (lastInteractionRef.current === "mouse") return;
    const el = listRef.current?.children[selectedIndex] as HTMLElement | undefined;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  if (!isOpen) return null;

  // Position the palette so it stays inside the viewport.
  const modalWidth = 340;
  const modalHeight = 420;
  const padding = 16;
  let left = position.x;
  let top = position.y - 25;

  if (source?.type === "target") {
    left = position.x - modalWidth;
  }
  if (left + modalWidth > window.innerWidth - padding) {
    left = position.x - modalWidth;
  }
  if (left < padding) left = padding;
  if (top + modalHeight > window.innerHeight - padding) {
    top = window.innerHeight - modalHeight - padding;
  }
  if (top < padding) top = padding;

  const headerHint = source
    ? source.type === "source"
      ? `Connect output → input`
      : `Connect input ← output`
    : "Add node";

  return (
    <div
      ref={modalRef}
      className="smart-connect-modal premium node-search-palette"
      style={{ position: "fixed", left, top, zIndex: 1000, width: modalWidth }}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="smart-connect-header">
        <div className="search-icon">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="11" cy="11" r="8" />
            <line x1="21" y1="21" x2="16.65" y2="16.65" />
          </svg>
        </div>
        <input
          ref={inputRef}
          type="text"
          placeholder={source ? "Search compatible nodes..." : "Search nodes... (Ctrl+K)"}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <div className="shortcut-hint" title={headerHint}>ESC</div>
      </div>

      <div className="smart-connect-list" ref={listRef}>
        {ranked.map((row, index) => {
          const node = row.node;
          const category = node.category || "Other";
          const catColor = getCategoryColor(category);
          return (
            <div
              key={node.node_type}
              className={`smart-connect-item ${index === selectedIndex ? "selected" : ""}`}
              style={{ ["--category-color" as string]: catColor }}
              onClick={() => onSelect(node)}
              onMouseEnter={() => {
                lastInteractionRef.current = "mouse";
                setSelectedIndex(index);
              }}
            >
              <div
                className="item-icon"
                style={{ background: `${catColor}22`, color: catColor, borderColor: `${catColor}44` }}
              >
                {getCategoryIcon(category)}
              </div>
              <div className="item-content">
                <div className="node-title-row">
                  <span
                    className="node-category"
                    style={{ background: `${catColor}18`, borderColor: `${catColor}33`, color: catColor }}
                  >
                    {category}
                  </span>
                  <span className="node-name">
                    <HighlightedText text={node.display_name} positions={row.positions} />
                  </span>
                  {row.matchedField === "tag" && (
                    <span className="match-field-badge" title="Matched a tag">tag</span>
                  )}
                  {row.matchedField === "node_type" && query && (
                    <span className="match-field-badge" title="Matched the node type id">id</span>
                  )}
                </div>
                <span className="node-desc">{node.description || node.summary || node.node_type}</span>
              </div>
              {index === selectedIndex && <span className="enter-hint">↵</span>}
            </div>
          );
        })}
        {ranked.length === 0 && (
          <div className="smart-connect-empty">
            <div className="empty-icon">?</div>
            <div>No matching nodes</div>
          </div>
        )}
      </div>
    </div>
  );
};

export default NodeSearchPalette;
