import React, { useMemo, useState } from "react";
import { GraphRecord } from "../api";

interface GraphLibraryProps {
  graphs: GraphRecord[];
  currentGraphId: string | null;
  isLoading: boolean;
  onCreate: (name: string) => void;
  onSelect: (graphId: string) => void;
  onRename: (graphId: string, name: string) => void;
  onDelete: (graphId: string) => void;
  onRefresh: () => void;
}

const GraphLibrary: React.FC<GraphLibraryProps> = ({
  graphs,
  currentGraphId,
  isLoading,
  onCreate,
  onSelect,
  onRename,
  onDelete,
  onRefresh,
}) => {
  const [newName, setNewName] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [isCollapsed, setIsCollapsed] = useState(false);

  const sortedGraphs = useMemo(() => {
    return [...graphs].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
  }, [graphs]);

  const handleCreate = () => {
    if (!newName.trim()) return;
    onCreate(newName.trim());
    setNewName("");
  };

  const handleRename = (graphId: string) => {
    if (!editingName.trim()) return;
    onRename(graphId, editingName.trim());
    setEditingId(null);
    setEditingName("");
  };

  return (
    <section className="graph-library">
      <div className="graph-library-header">
        <button
          type="button"
          className={`graph-library-toggle ${isCollapsed ? "collapsed" : ""}`}
          onClick={() => setIsCollapsed((prev) => !prev)}
        >
          <span>Graphs</span>
          <span className="graph-library-count">{graphs.length}</span>
        </button>
        <button className="graph-library-refresh" type="button" onClick={onRefresh} title="Refresh graphs">
          ↻
        </button>
      </div>

      {!isCollapsed && (
        <>
          <div className="graph-library-new">
            <input
              type="text"
              placeholder="New graph name"
              value={newName}
              onChange={(event) => setNewName(event.target.value)}
              onKeyDown={(event) => event.key === "Enter" && handleCreate()}
            />
            <button type="button" onClick={handleCreate}>
              Create
            </button>
          </div>

          <div className="graph-library-list">
            {isLoading && <div className="graph-library-empty">Loading graphs...</div>}
            {!isLoading && sortedGraphs.length === 0 && (
              <div className="graph-library-empty">No graphs yet. Create one above.</div>
            )}
            {sortedGraphs.map((graph) => (
              <div
                key={graph.id}
                className={`graph-library-item ${currentGraphId === graph.id ? "active" : ""}`}
              >
                {editingId === graph.id ? (
                  <input
                    type="text"
                    value={editingName}
                    onChange={(event) => setEditingName(event.target.value)}
                    onKeyDown={(event) => event.key === "Enter" && handleRename(graph.id)}
                    onBlur={() => setEditingId(null)}
                    autoFocus
                  />
                ) : (
                  <button type="button" className="graph-library-name" onClick={() => onSelect(graph.id)}>
                    {graph.name}
                  </button>
                )}
                <div className="graph-library-actions">
                  <button
                    type="button"
                    onClick={() => {
                      setEditingId(graph.id);
                      setEditingName(graph.name);
                    }}
                  >
                    Rename
                  </button>
                  <button type="button" className="danger" onClick={() => onDelete(graph.id)}>
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        </>
      )}
    </section>
  );
};

export default GraphLibrary;
