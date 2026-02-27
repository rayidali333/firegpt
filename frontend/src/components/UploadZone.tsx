import React, { useCallback, useRef, useState } from "react";
import { Upload } from "lucide-react";

interface Props {
  onUpload: (file: File) => void;
  uploading: boolean;
  error: string | null;
}

export default function UploadZone({ onUpload, uploading, error }: Props) {
  const [dragOver, setDragOver] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

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
            <p>Parsing drawing symbols...</p>
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
