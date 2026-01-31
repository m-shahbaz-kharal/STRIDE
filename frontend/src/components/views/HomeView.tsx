import React from "react";
import GraphLibrary from "../GraphLibrary";
import { GraphRecord } from "../../api";

interface HomeViewProps {
  graphs: GraphRecord[];
  currentGraphId: string | null;
  isLoading: boolean;
  onCreate: (name: string, description: string) => Promise<void>;
  onSelect: (graphId: string) => void;
  onUpdate: (graphId: string, name: string, description: string) => Promise<void>;
  onDelete: (graphId: string) => Promise<void>;
  visible: boolean;
}

const HomeView: React.FC<HomeViewProps> = ({
  graphs,
  currentGraphId,
  isLoading,
  onCreate,
  onSelect,
  onUpdate,
  onDelete,
  visible,
}) => {
  return (
    <div
      className="home-fullpage"
      style={{ display: visible ? "flex" : "none" }}
    >
      <GraphLibrary
        graphs={graphs}
        currentGraphId={currentGraphId}
        isLoading={isLoading}
        onCreate={onCreate}
        onSelect={onSelect}
        onUpdate={onUpdate}
        onDelete={onDelete}
      />
    </div>
  );
};

export default HomeView;
