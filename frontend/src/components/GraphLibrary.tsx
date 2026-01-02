import React, { useMemo, useState } from "react";
import { GraphRecord } from "../api";
import { CloseIcon, DeleteIcon, EditIcon, PlusIcon } from "./Icons";

interface GraphLibraryProps {
  graphs: GraphRecord[];
  currentGraphId: string | null;
  isLoading: boolean;
  onCreate: (name: string, description: string) => void;
  onSelect: (graphId: string) => void;
  onUpdate: (graphId: string, name: string, description: string) => void;
  onDelete: (graphId: string) => void;
}

const GraphLibrary: React.FC<GraphLibraryProps> = ({
  graphs,
  currentGraphId,
  isLoading,
  onCreate,
  onSelect,
  onUpdate,
  onDelete,
}) => {
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editorMode, setEditorMode] = useState<"create" | "edit">("create");
  const [editorName, setEditorName] = useState("");
  const [editorDescription, setEditorDescription] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [deleteConfirm, setDeleteConfirm] = useState("");
  const [search, setSearch] = useState("");

  const filteredGraphs = useMemo(() => {
    const query = search.trim().toLowerCase();
    const list = [...graphs].sort((a, b) => b.updated_at.localeCompare(a.updated_at));
    if (!query) return list;
    return list.filter((graph) =>
      `${graph.name} ${graph.description ?? ""}`.toLowerCase().includes(query)
    );
  }, [graphs, search]);

  const openCreate = () => {
    setEditorMode("create");
    setEditorName("");
    setEditorDescription("");
    setEditingId(null);
    setIsEditorOpen(true);
  };

  const openEdit = (graph: GraphRecord) => {
    setEditorMode("edit");
    setEditorName(graph.name);
    setEditorDescription(graph.description ?? "");
    setEditingId(graph.id);
    setIsEditorOpen(true);
  };

  const submitEditor = () => {
    if (!editorName.trim()) return;
    if (editorMode === "create") {
      onCreate(editorName.trim(), editorDescription.trim());
    } else if (editingId) {
      onUpdate(editingId, editorName.trim(), editorDescription.trim());
    }
    setIsEditorOpen(false);
  };

  const confirmDelete = () => {
    if (!deleteId) return;
    const target = graphs.find((graph) => graph.id === deleteId);
    if (!target) return;
    if (deleteConfirm.trim() !== target.name) return;
    onDelete(deleteId);
    setDeleteId(null);
    setDeleteConfirm("");
  };

  return (
    <section className="graph-home">
      <div className="graph-home-header">
        <div>
          <p className="graph-home-eyebrow">LiGuard DT</p>
          <h2>Graphs</h2>
          <p className="graph-home-subtitle">Create, edit, and manage your saved node graphs.</p>
        </div>
        <div className="graph-home-actions">
          <button className="primary-btn icon" type="button" onClick={openCreate} aria-label="New graph">
            <PlusIcon />
          </button>
        </div>
      </div>

      <div className="graph-home-search">
        <input
          type="text"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search graphs"
        />
      </div>

      <div className="graph-home-list">
        {isLoading && <div className="graph-home-empty">Loading graphs...</div>}
        {!isLoading && filteredGraphs.length === 0 && (
          <div className="graph-home-empty">No graphs found. Try a different search.</div>
        )}
        {filteredGraphs.map((graph) => (
          <div
            key={graph.id}
            className={`graph-home-item ${currentGraphId === graph.id ? "active" : ""}`}
          >
            <button type="button" className="graph-home-main" onClick={() => onSelect(graph.id)}>
              <div>
                <h3>{graph.name}</h3>
                <p>{graph.description || "No description"}</p>
              </div>
            </button>
            <div className="graph-home-item-actions">
              <button type="button" onClick={() => openEdit(graph)} title="Edit">
                <EditIcon />
              </button>
              <button type="button" className="danger" onClick={() => setDeleteId(graph.id)} title="Delete">
                <DeleteIcon />
              </button>
            </div>
          </div>
        ))}
      </div>

      {isEditorOpen && (
        <div className="modal-overlay">
          <div className="modal-card">
            <div className="modal-header">
              <h3>{editorMode === "create" ? "Create graph" : "Edit graph"}</h3>
              <button type="button" className="icon-btn" onClick={() => setIsEditorOpen(false)}>
                <CloseIcon />
              </button>
            </div>
            <div className="modal-body">
              <label>
                <span>Name</span>
                <input
                  type="text"
                  value={editorName}
                  onChange={(event) => setEditorName(event.target.value)}
                  placeholder="Graph name"
                />
              </label>
              <label>
                <span>Description</span>
                <textarea
                  value={editorDescription}
                  onChange={(event) => setEditorDescription(event.target.value)}
                  placeholder="Short description"
                />
              </label>
            </div>
            <div className="modal-actions">
              <button type="button" className="ghost-btn" onClick={() => setIsEditorOpen(false)}>
                Cancel
              </button>
              <button type="button" className="primary-btn" onClick={submitEditor}>
                {editorMode === "create" ? "Create graph" : "Save changes"}
              </button>
            </div>
          </div>
        </div>
      )}

      {deleteId && (
        <div className="modal-overlay">
          <div className="modal-card danger">
            <div className="modal-header">
              <h3>Delete graph</h3>
              <button type="button" className="icon-btn" onClick={() => setDeleteId(null)}>
                <CloseIcon />
              </button>
            </div>
            <div className="modal-body">
              <p>
                To confirm deletion, type the graph name <strong>{graphs.find((graph) => graph.id === deleteId)?.name ?? ""}</strong>.
              </p>
              <input
                type="text"
                value={deleteConfirm}
                onChange={(event) => setDeleteConfirm(event.target.value)}
                placeholder="Graph name"
              />
            </div>
            <div className="modal-actions">
              <button type="button" className="ghost-btn" onClick={() => setDeleteId(null)}>
                Cancel
              </button>
              <button
                type="button"
                className="danger-btn"
                onClick={confirmDelete}
                disabled={!deleteConfirm.trim()}
              >
                Delete
              </button>
            </div>
          </div>
        </div>
      )}
    </section>
  );
};

export default GraphLibrary;
