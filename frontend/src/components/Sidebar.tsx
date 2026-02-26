import React, { useRef } from "react";
import { Upload, FileText } from "lucide-react";
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
          Drawing<span className="sidebar-logo-accent">IQ</span>
        </div>
        <div className="sidebar-tagline">Fire Alarm Symbol Analysis</div>
      </div>

      <div className="sidebar-section">
        <button
          className="sidebar-upload-btn"
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
        >
          <Upload />
          {uploading ? "Parsing..." : "Upload Drawing"}
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".dxf,.dwg"
          onChange={handleChange}
          style={{ display: "none" }}
        />
      </div>

      <div className="sidebar-section">
        <div className="sidebar-section-title">Your Drawings</div>
        {drawing ? (
          <div className="sidebar-file-list">
            <div className="sidebar-file active">
              <FileText />
              <span className="sidebar-file-name">{drawing.filename}</span>
            </div>
          </div>
        ) : (
          <div className="sidebar-empty">No drawings yet</div>
        )}
      </div>

      {drawing && (
        <div className="sidebar-section sidebar-bottom">
          <button className="sidebar-reset-btn" onClick={onReset}>
            New Drawing
          </button>
        </div>
      )}
    </aside>
  );
}
