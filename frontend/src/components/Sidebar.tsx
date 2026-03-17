import React, { useRef } from "react";
import {
  Upload,
  FileText,
  MessageSquare,
  BarChart3,
  Eye,
  Flame,
  ClipboardList,
  BookOpen,
  Layers,
} from "lucide-react";
import { DrawingData, LegendData, ProjectData } from "../types";

interface Props {
  drawing: DrawingData | null;
  onUpload: (file: File) => void;
  uploading: boolean;
  onReset: () => void;
  messageCount: number;
  activeTab: "symbols" | "drawing" | "analysis" | "legend";
  onTabChange: (tab: "symbols" | "drawing" | "analysis" | "legend") => void;
  legend: LegendData | null;
  project: ProjectData | null;
  projectDrawings: Map<string, DrawingData>;
  onSelectSheet: (drawingId: string) => void;
}

export default function Sidebar({
  drawing,
  onUpload,
  uploading,
  onReset,
  messageCount,
  activeTab,
  onTabChange,
  legend,
  project,
  projectDrawings,
  onSelectSheet,
}: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const ext = file.name.toLowerCase().split(".").pop();
      if (ext === "dxf" || ext === "dwg") {
        onUpload(file);
      }
    }
    // Reset input so same file can be re-uploaded
    e.target.value = "";
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          <Flame className="sidebar-logo-icon" />
          <span>
            Fire<span className="sidebar-logo-accent">GPT</span>
          </span>
        </div>
        <div className="sidebar-tagline">Talk to your drawing files</div>
      </div>

      <div className="sidebar-section">
        <div
          className="sidebar-nav-item upload-nav"
          onClick={() => inputRef.current?.click()}
          style={{ cursor: "pointer" }}
        >
          <Upload />
          <span>{uploading ? "Analyzing..." : "Upload Drawing"}</span>
        </div>
        <input
          ref={inputRef}
          type="file"
          accept=".dxf,.dwg"
          onChange={handleChange}
          style={{ display: "none" }}
        />
      </div>

      {legend && (
        <div className="sidebar-section">
          <div className="sidebar-section-title">
            <span className="sidebar-section-arrow">&#9660;</span>
            Legend
          </div>
          <div
            className={`sidebar-nav-item ${drawing && activeTab === "legend" ? "active" : ""}`}
            onClick={() => drawing && onTabChange("legend")}
            style={{ cursor: drawing ? "pointer" : "default" }}
          >
            <BookOpen />
            <span className="sidebar-file-name">{legend.filename}</span>
            <span className="sidebar-badge">{legend.total_symbols}</span>
          </div>
        </div>
      )}

      <div className="sidebar-section">
        <div className="sidebar-section-title">
          <span className="sidebar-section-arrow">&#9660;</span>
          {project ? (
            <>
              <Layers style={{ width: 12, height: 12, marginRight: 4 }} />
              Sheets ({project.drawing_ids.length})
            </>
          ) : (
            "Drawings"
          )}
        </div>
        {project ? (
          // Project mode — show all sheets, highlight active one
          project.drawing_ids.map((did) => {
            const d = projectDrawings.get(did);
            const isActive = drawing?.drawing_id === did;
            return (
              <div
                key={did}
                className={`sidebar-nav-item ${isActive ? "active" : ""}`}
                onClick={() => onSelectSheet(did)}
                style={{ cursor: "pointer" }}
              >
                <FileText />
                <span className="sidebar-file-name">
                  {d?.filename || did.slice(0, 8) + "..."}
                </span>
                {d && (
                  <span className="sidebar-badge">{d.total_symbols}</span>
                )}
              </div>
            );
          })
        ) : drawing ? (
          <div className="sidebar-nav-item active">
            <FileText />
            <span className="sidebar-file-name">{drawing.filename}</span>
          </div>
        ) : (
          <div className="sidebar-empty">No drawings yet</div>
        )}
      </div>

      {drawing && (
        <div className="sidebar-section">
          <div className="sidebar-section-title">
            <span className="sidebar-section-arrow">&#9660;</span>
            Views
          </div>
          <div
            className={`sidebar-nav-item ${activeTab === "symbols" ? "active" : ""}`}
            onClick={() => onTabChange("symbols")}
          >
            <BarChart3 />
            <span>Symbols</span>
            <span className="sidebar-badge">{drawing.total_symbols}</span>
          </div>
          <div
            className={`sidebar-nav-item ${activeTab === "drawing" ? "active" : ""}`}
            onClick={() => onTabChange("drawing")}
          >
            <Eye />
            <span>Drawing</span>
          </div>
          <div
            className={`sidebar-nav-item ${activeTab === "analysis" ? "active" : ""}`}
            onClick={() => onTabChange("analysis")}
          >
            <ClipboardList />
            <span>Analysis</span>
            <span className="sidebar-badge">{drawing.analysis?.length || 0}</span>
          </div>
          <div className="sidebar-nav-item">
            <MessageSquare />
            <span>Chat</span>
            <span className="sidebar-badge">{messageCount}</span>
          </div>
        </div>
      )}

      {drawing && (
        <div className="sidebar-bottom">
          <div className="sidebar-stats">
            {project ? (
              <>
                <div className="sidebar-stat">
                  <span className="stat-value">{project.drawing_ids.length}</span>
                  <span className="stat-label">Sheets</span>
                </div>
                <div className="sidebar-stat">
                  <span className="stat-value">
                    {Array.from(projectDrawings.values()).reduce(
                      (sum, d) => sum + d.total_symbols, 0
                    )}
                  </span>
                  <span className="stat-label">Total</span>
                </div>
              </>
            ) : (
              <>
                <div className="sidebar-stat">
                  <span className="stat-value">
                    {drawing.symbols.length}
                  </span>
                  <span className="stat-label">Types</span>
                </div>
                <div className="sidebar-stat">
                  <span className="stat-value">{drawing.total_symbols}</span>
                  <span className="stat-label">Devices</span>
                </div>
              </>
            )}
          </div>
          <button className="sidebar-action-btn" onClick={onReset}>
            New {project ? "Project" : "Drawing"}
          </button>
        </div>
      )}
    </aside>
  );
}
