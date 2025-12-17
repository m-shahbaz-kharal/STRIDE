import React, { useEffect, useMemo, useState } from "react";
import { Node } from "reactflow";
import { BlueprintNodeData } from "../types";

interface OutputsViewProps {
  nodes: Node<BlueprintNodeData>[];
  outputs: Record<string, unknown>;
}

const OutputsView: React.FC<OutputsViewProps> = ({ nodes, outputs }) => {
  const [refreshToken, setRefreshToken] = useState(0);

  const formatValue = (val: unknown): string => {
    if (val === null) return "null";
    if (val === undefined) return "undefined";
    if (typeof val === "string") return val;
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    return JSON.stringify(val, null, 2);
  };

  // Find all display nodes and their outputs
  const { displayOutputs, valueOutputs, streamIds } = useMemo(() => {
    const displayNodes = nodes.filter((node) => node.data.nodeType === "display.image");

    const images: Array<{ nodeId: string; nodeName: string; image: string }> = [];
    const values: Array<{ key: string; value: unknown }> = [];
    const streams: string[] = [];

    for (const node of displayNodes) {
      const nodeOutputs = node.data.last_outputs;
      if (nodeOutputs?.display) {
        const image = nodeOutputs.display as string;
        if (typeof image === "string" && image.startsWith("data:image")) {
          images.push({
            nodeId: node.id,
            nodeName: node.data.displayName,
            image,
          });
        }
      }
    }

    for (const [key, value] of Object.entries(outputs)) {
      if (typeof value === "string" && value.startsWith("data:image")) {
        images.push({
          nodeId: key.split(".")[0] || key,
          nodeName: key,
          image: value,
        });
      } else if (key.toLowerCase().includes("stream_id") && typeof value === "string") {
        streams.push(value);
      } else {
        values.push({ key, value });
      }
    }

    return { displayOutputs: images, valueOutputs: values, streamIds: streams };
  }, [nodes, outputs]);

  // Heartbeat to refresh live stream images
  useEffect(() => {
    if (streamIds.length === 0) return;
    const interval = window.setInterval(() => {
      setRefreshToken((prev) => prev + 1);
    }, 500);
    return () => window.clearInterval(interval);
  }, [streamIds]);

  if (displayOutputs.length === 0 && valueOutputs.length === 0) {
    return (
      <div className="outputs-view">
        <div className="outputs-empty">
          <svg width="64" height="64" viewBox="0 0 24 24" fill="currentColor" style={{ opacity: 0.3 }}>
            <path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z" />
          </svg>
          <p>No images to display</p>
          <p className="outputs-empty-hint">
            Add a "Display Image" node and connect an image source to see outputs here.
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="outputs-view">
      {displayOutputs.length > 0 && (
        <>
          <div className="outputs-header">
            <h2>Image Outputs</h2>
            <span className="outputs-count">{displayOutputs.length} image{displayOutputs.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="outputs-grid">
            {displayOutputs.map((output, index) => (
              <div key={`${output.nodeId}-${index}`} className="output-item">
                <div className="output-item-header">
                  <span className="output-item-title">{output.nodeName}</span>
                  <span className="output-item-id">{output.nodeId}</span>
                </div>
                <div className="output-item-image-container">
                  <img
                    src={output.image}
                    alt={`Output from ${output.nodeName}`}
                    className="output-item-image"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      target.style.display = "none";
                      const errorDiv = document.createElement("div");
                      errorDiv.className = "output-item-error";
                      errorDiv.textContent = "Failed to load image";
                      target.parentElement?.appendChild(errorDiv);
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {streamIds.length > 0 && (
        <>
          <div className="outputs-header">
            <h2>Live Streams</h2>
            <span className="outputs-count">{streamIds.length}</span>
          </div>
          <div className="outputs-grid">
            {streamIds.map((id) => (
              <div key={id} className="output-item live">
                <div className="output-item-header">
                  <span className="output-item-title">Stream {id}</span>
                  <span className="output-item-id">camera.stream_start</span>
                </div>
                <div className="output-item-image-container">
                  <img
                    src={`/api/streams/${id}/frame?ts=${refreshToken}`}
                    alt="Live stream"
                    className="output-item-image"
                    onError={(e) => {
                      const target = e.target as HTMLImageElement;
                      target.style.opacity = "0.5";
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        </>
      )}

      {valueOutputs.length > 0 && (
        <>
          <div className="outputs-header">
            <h2>Value Outputs</h2>
            <span className="outputs-count">{valueOutputs.length}</span>
          </div>
          <div className="outputs-values-grid">
            {valueOutputs.map(({ key, value }) => (
              <div key={key} className="output-value-card">
                <div className="output-item-header">
                  <span className="output-item-title">{key}</span>
                </div>
                <pre className="output-value-body">{formatValue(value)}</pre>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

export default OutputsView;
