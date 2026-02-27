import React, { useRef } from "react";
import { Upload, FileText, MessageSquare, BarChart3 } from "lucide-react";
import { DrawingData } from "../types";

interface Props {
  drawing: DrawingData | null;
  onUpload: (file: File) => void;
  uploading: boolean;
  onReset: () => void;
}

export default function Sidebar({ drawing, onUpload, uploading, onReset }: Props) {
  const inputRef = useRef<HTMLInputElement>(null);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const ext = file.name.toLowerCase().split(".").pop();
      if (ext === "dxf" || ext === "dwg") {
        onUpload(file);
      }
    }
  };

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="sidebar-logo">
          Fire<span className="sidebar-logo-accent">GPT</span>
          <span className="sidebar-dropdown-arrow">&#9660;</span>
        </div>
        <div className="sidebar-tagline">Fire Alarm Analysis</div>
      </div>

      <div className="sidebar-section">
        <div
          className="sidebar-nav-item"
          onClick={() => inputRef.current?.click()}
          style={{ cursor: "pointer" }}
        >
          <Upload />
          <span>{uploading ? "Parsing..." : "Upload Drawing"}</span>
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

      <div className="sidebar-section">
        <div className="sidebar-section-title">
          <span className="sidebar-section-arrow">&#9660;</span>
          Analysis
        </div>
        <div className={`sidebar-nav-item ${drawing ? "" : ""}`}>
          <BarChart3 />
          <span><span className="nav-prefix">#</span> symbols</span>
        </div>
        <div className="sidebar-nav-item">
          <MessageSquare />
          <span><span className="nav-prefix">#</span> chat</span>
        </div>
      </div>

      {drawing && (
        <div className="sidebar-bottom">
          <button className="sidebar-action-btn" onClick={onReset}>
            New Drawing
          </button>
        </div>
      )}
    </aside>
  );
}
