import React, { useEffect, useMemo, useState } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData } from "../types";

interface OutputsViewProps {
  nodes: Node<BlueprintNodeData>[];
  outputs: Record<string, unknown>;
}

type ImageOutput = { nodeId: string; nodeName: string; image: string; source: "node" | "graph" };
type ValueOutput = { key: string; value: unknown };

const OutputsView: React.FC<OutputsViewProps> = ({ nodes, outputs }) => {
  const [refreshToken, setRefreshToken] = useState(0);

  const formatValue = (val: unknown): string => {
    if (val === null) return "null";
    if (val === undefined) return "undefined";
    if (typeof val === "string") return val;
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    return JSON.stringify(val, null, 2);
  };

  // Collect typed outputs from graph + display nodes
  const { images, values, streams } = useMemo(() => {
    const img: ImageOutput[] = [];
    const val: ValueOutput[] = [];
    const streamIds: string[] = [];

    // Inline display nodes
    for (const node of nodes) {
      const nodeOutputs = node.data.last_outputs;
      if (nodeOutputs?.display && typeof nodeOutputs.display === "string" && nodeOutputs.display.startsWith("data:image")) {
        img.push({
          nodeId: node.id,
          nodeName: node.data.displayName,
          image: nodeOutputs.display,
          source: "node",
        });
      }
    }

    // Graph-level outputs
    for (const [key, value] of Object.entries(outputs)) {
      if (typeof value === "string" && value.startsWith("data:image")) {
        img.push({
          nodeId: key.split(".")[0] || key,
          nodeName: key,
          image: value,
          source: "graph",
        });
      } else if (typeof value === "string" && key.toLowerCase().includes("stream_id")) {
        streamIds.push(value);
      } else {
        val.push({ key, value });
      }
    }

    return { images: img, values: val, streams: streamIds };
  }, [nodes, outputs]);

  // Heartbeat refresh for stream snapshots
  useEffect(() => {
    if (streams.length === 0) return;
    const interval = window.setInterval(() => setRefreshToken((prev) => prev + 1), 500);
    return () => window.clearInterval(interval);
  }, [streams]);

  const hasContent = images.length > 0 || values.length > 0 || streams.length > 0;

  if (!hasContent) {
    return (
      <div className="outputs-view">
        <div className="outputs-empty">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor" style={{ opacity: 0.3 }}>
            <path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z" />
          </svg>
          <p>No outputs yet</p>
          <p className="outputs-empty-hint">Run a graph or attach a Display node to see live results.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="outputs-view">
      <div className="outputs-hero">
        <div>
          <p className="eyebrow">Captured Outputs</p>
          <h2>Live canvas for your runs</h2>
          <div className="outputs-pills">
            <span className="pill">{images.length} image{images.length === 1 ? "" : "s"}</span>
            <span className="pill">{streams.length} stream{streams.length === 1 ? "" : "s"}</span>
            <span className="pill">{values.length} value{values.length === 1 ? "" : "s"}</span>
          </div>
        </div>
        <div className="outputs-legend">
          <span className="legend-dot live" /> Live stream
          <span className="legend-sep">•</span>
          <span className="legend-dot capture" /> Captured frame/value
        </div>
      </div>

      {streams.length > 0 && (
        <section className="outputs-section">
          <div className="outputs-header">
            <div>
              <p className="eyebrow">Streaming</p>
              <h3>Live feeds</h3>
            </div>
            <span className="outputs-count">{streams.length}</span>
          </div>
          <div className="outputs-grid">
            {streams.map((id) => (
              <div key={id} className="output-card stream">
                <div className="output-card__bar">
                  <span className="badge live">LIVE</span>
                  <span className="meta">camera.stream_start</span>
                  <span className="mono">#{id}</span>
                </div>
                <div className="output-card__body">
                  <img
                    src={`/api/streams/${id}/frame?ts=${refreshToken}`}
                    alt="Live stream"
                    className="output-card__media"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      target.style.opacity = "0.45";
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {images.length > 0 && (
        <section className="outputs-section">
          <div className="outputs-header">
            <div>
              <p className="eyebrow">Frames</p>
              <h3>Image outputs</h3>
            </div>
            <span className="outputs-count">{images.length}</span>
          </div>
          <div className="outputs-grid">
            {images.map((output, index) => (
              <div key={`${output.nodeId}-${index}`} className="output-card image">
                <div className="output-card__bar">
                  <span className="badge subtle">{output.source === "node" ? "Node" : "Graph"}</span>
                  <span className="meta">{output.nodeName}</span>
                  <span className="mono">{output.nodeId}</span>
                </div>
                <div className="output-card__body">
                  <img
                    src={output.image}
                    alt={`Output from ${output.nodeName}`}
                    className="output-card__media"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      target.style.display = "none";
                      const fallback = target.parentElement;
                      if (fallback) {
                        const div = document.createElement("div");
                        div.className = "output-item-error";
                        div.textContent = "Failed to load image";
                        fallback.appendChild(div);
                      }
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {values.length > 0 && (
        <section className="outputs-section">
          <div className="outputs-header">
            <div>
              <p className="eyebrow">Scalars</p>
              <h3>Value outputs</h3>
            </div>
            <span className="outputs-count">{values.length}</span>
          </div>
          <div className="outputs-values-grid">
            {values.map(({ key, value }) => (
              <div key={key} className="output-value-card">
                <div className="output-item-header">
                  <span className="output-item-title">{key}</span>
                  <span className="badge subtle">capture</span>
                </div>
                <pre className="output-value-body">{formatValue(value)}</pre>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
};

export default OutputsView;
