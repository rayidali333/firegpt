import React, { useRef } from "react";
import {
  Upload,
  FileText,
  MessageSquare,
  BarChart3,
  Eye,
  Flame,
  ClipboardList,
} from "lucide-react";
import { DrawingData } from "../types";

interface Props {
  drawing: DrawingData | null;
  onUpload: (file: File) => void;
  uploading: boolean;
  onReset: () => void;
  messageCount: number;
  activeTab: "symbols" | "drawing" | "analysis";
  onTabChange: (tab: "symbols" | "drawing" | "analysis") => void;
}

export default function Sidebar({
  drawing,
  onUpload,
  uploading,
  onReset,
  messageCount,
  activeTab,
  onTabChange,
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

      <div className="sidebar-section">
        <div className="sidebar-section-title">
          <span className="sidebar-section-arrow">&#9660;</span>
          Drawings
        </div>
        {drawing ? (
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
          </div>
          <button className="sidebar-action-btn" onClick={onReset}>
            New Drawing
          </button>
        </div>
      )}
    </aside>
  );
}
