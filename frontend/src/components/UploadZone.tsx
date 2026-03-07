import React, { useCallback, useEffect, useRef, useState } from "react";
import { Upload } from "lucide-react";

interface Props {
  onUpload: (file: File) => void;
  uploading: boolean;
  error: string | null;
}

export default function UploadZone({ onUpload, uploading, error }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("");

  useEffect(() => {
    if (!uploading) {
      setProgress(0);
      setStage("");
      return;
    }
    setProgress(0);
    setStage("Reading file...");

    const stages = [
      { at: 8, label: "Uploading drawing file..." },
      { at: 18, label: "Converting to DXF format..." },
      { at: 30, label: "Scanning block definitions..." },
      { at: 42, label: "Detecting INSERT entities..." },
      { at: 52, label: "Matching known symbol patterns..." },
      { at: 62, label: "Classifying unknown blocks with AI..." },
      { at: 72, label: "Resolving XREF prefixes..." },
      { at: 80, label: "Consolidating symbol variants..." },
      { at: 88, label: "Counting devices and building summary..." },
      { at: 93, label: "Finalizing symbol table..." },
    ];

    let p = 0;
    const interval = setInterval(() => {
      const remaining = 95 - p;
      const increment = Math.max(0.25, remaining * 0.035);
      p = Math.min(95, p + increment);
      setProgress(p);

      const s = [...stages].reverse().find((s) => p >= s.at);
      if (s) setStage(s.label);
    }, 200);

    return () => clearInterval(interval);
  }, [uploading]);

  const handleFile = useCallback(
    (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop();
      if (ext !== "dxf" && ext !== "dwg") {
        return;
      }
      onUpload(file);
    },
    [onUpload]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) handleFile(file);
    },
    [handleFile]
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleClick = () => inputRef.current?.click();

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="upload-container">
      <div
        className={`upload-zone ${dragOver ? "drag-over" : ""} ${
          uploading ? "uploading" : ""
        }`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={handleClick}
      >
        {uploading ? (
          <div className="upload-spinner">
            <div className="spinner" />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>Analyzing drawing...</p>
            <div className="preview-progress-bar" style={{ width: 240 }}>
              <div
                className="preview-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="preview-progress-stage">{stage}</p>
            <p className="preview-progress-hint">Large drawings may take up to a minute</p>
          </div>
        ) : (
          <>
            <Upload className="upload-icon" />
            <h2 className="upload-title">Upload a Construction Drawing</h2>
            <p className="upload-subtitle">
              Drop your DXF or DWG file here, or click to browse.
              <br />
              FireGPT will detect and count all fire alarm symbols.
            </p>
            <div className="upload-formats">
              <span className="format-badge">.DXF</span>
              <span className="format-badge">.DWG</span>
            </div>
          </>
        )}
        {error && <div className="upload-error">{error}</div>}
        <input
          ref={inputRef}
          type="file"
          accept=".dxf,.dwg"
          onChange={handleChange}
          style={{ display: "none" }}
        />
      </div>
    </div>
  );
}
