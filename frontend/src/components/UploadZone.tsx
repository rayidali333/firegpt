import React, { useCallback, useEffect, useRef, useState } from "react";
import { Upload, BookOpen, CheckCircle, SkipForward } from "lucide-react";
import { LegendData } from "../types";

interface Props {
  onUpload: (file: File) => void;
  uploading: boolean;
  error: string | null;
  legend: LegendData | null;
  legendUploading: boolean;
  legendSkipped: boolean;
  onLegendUpload: (file: File) => void;
  onLegendSkip: () => void;
}

export default function UploadZone({
  onUpload,
  uploading,
  error,
  legend,
  legendUploading,
  legendSkipped,
  onLegendUpload,
  onLegendSkip,
}: Props) {
  const [dragOver, setDragOver] = useState(false);
  const drawingInputRef = useRef<HTMLInputElement>(null);
  const legendInputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("");

  // Show step 2 (drawing upload) when legend is uploaded or skipped
  const showDrawingUpload = legend !== null || legendSkipped;

  useEffect(() => {
    if (!uploading && !legendUploading) {
      setProgress(0);
      setStage("");
      return;
    }

    if (legendUploading) {
      setProgress(0);
      setStage("Uploading legend file...");
      const legendStages = [
        { at: 10, label: "Uploading legend file..." },
        { at: 25, label: "Converting to images..." },
        { at: 40, label: "Sending to Claude Vision..." },
        { at: 60, label: "Analyzing symbols and devices..." },
        { at: 75, label: "Extracting device descriptions..." },
        { at: 88, label: "Building device catalog..." },
      ];

      let p = 0;
      const interval = setInterval(() => {
        const remaining = 95 - p;
        const increment = Math.max(0.25, remaining * 0.03);
        p = Math.min(95, p + increment);
        setProgress(p);
        const s = [...legendStages].reverse().find((s) => p >= s.at);
        if (s) setStage(s.label);
      }, 200);
      return () => clearInterval(interval);
    }

    if (uploading) {
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
    }
  }, [uploading, legendUploading]);

  const handleDrawingFile = useCallback(
    (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop();
      if (ext !== "dxf" && ext !== "dwg") return;
      onUpload(file);
    },
    [onUpload]
  );

  const handleLegendFile = useCallback(
    (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop();
      const allowed = ["pdf", "png", "jpg", "jpeg", "gif", "webp"];
      if (!ext || !allowed.includes(ext)) return;
      onLegendUpload(file);
    },
    [onLegendUpload]
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      const file = e.dataTransfer.files[0];
      if (!file) return;

      if (showDrawingUpload) {
        handleDrawingFile(file);
      } else {
        // On step 1, accept legend files OR drawing files
        const ext = file.name.toLowerCase().split(".").pop();
        if (ext === "dxf" || ext === "dwg") {
          // They dropped a drawing — skip legend step
          onLegendSkip();
          onUpload(file);
        } else {
          handleLegendFile(file);
        }
      }
    },
    [showDrawingUpload, handleDrawingFile, handleLegendFile, onLegendSkip, onUpload]
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const isLoading = uploading || legendUploading;

  // ── Loading state ──
  if (isLoading) {
    return (
      <div className="upload-container">
        <div className="upload-zone uploading">
          <div className="upload-spinner">
            <div className="spinner" />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>
              {legendUploading ? "Analyzing legend..." : "Analyzing drawing..."}
            </p>
            <div className="preview-progress-bar" style={{ width: 240 }}>
              <div
                className="preview-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="preview-progress-stage">{stage}</p>
            <p className="preview-progress-hint">
              {legendUploading
                ? "Claude Vision is reading every symbol in the legend"
                : "Large drawings may take up to a minute"}
            </p>
          </div>
          {error && <div className="upload-error">{error}</div>}
        </div>
      </div>
    );
  }

  // ── Step 2: Drawing upload (legend done or skipped) ──
  if (showDrawingUpload) {
    return (
      <div className="upload-container">
        {/* Legend success indicator */}
        {legend && (
          <div className="legend-success-banner">
            <CheckCircle size={16} />
            <span>
              Legend loaded: <strong>{legend.filename}</strong> —{" "}
              {legend.total_device_types} device types found
            </span>
          </div>
        )}

        <div
          className={`upload-zone ${dragOver ? "drag-over" : ""}`}
          onDrop={handleDrop}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onClick={() => drawingInputRef.current?.click()}
        >
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
          {error && <div className="upload-error">{error}</div>}
          <input
            ref={drawingInputRef}
            type="file"
            accept=".dxf,.dwg"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) handleDrawingFile(file);
            }}
            style={{ display: "none" }}
          />
        </div>

        <div className="upload-step-indicator">
          <span className="step-dot completed" />
          <span className="step-line" />
          <span className="step-dot active" />
          <span className="step-label">Step 2 of 2: Upload Drawing</span>
        </div>
      </div>
    );
  }

  // ── Step 1: Legend upload (optional) ──
  return (
    <div className="upload-container">
      <div
        className={`upload-zone legend-step ${dragOver ? "drag-over" : ""}`}
        onDrop={handleDrop}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onClick={() => legendInputRef.current?.click()}
      >
        <BookOpen className="upload-icon" />
        <h2 className="upload-title">Upload a Legend (Optional)</h2>
        <p className="upload-subtitle">
          Upload the drawing legend/symbol key as a PDF or image.
          <br />
          AI will extract all device types and symbol descriptions.
        </p>
        <div className="upload-formats">
          <span className="format-badge">.PDF</span>
          <span className="format-badge">.PNG</span>
          <span className="format-badge">.JPG</span>
        </div>
        {error && <div className="upload-error">{error}</div>}
        <input
          ref={legendInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) handleLegendFile(file);
          }}
          style={{ display: "none" }}
        />
      </div>

      <button className="legend-skip-btn" onClick={onLegendSkip}>
        <SkipForward size={14} />
        Skip — upload drawing without legend
      </button>

      <div className="upload-step-indicator">
        <span className="step-dot active" />
        <span className="step-line" />
        <span className="step-dot" />
        <span className="step-label">Step 1 of 2: Legend (Optional)</span>
      </div>
    </div>
  );
}
