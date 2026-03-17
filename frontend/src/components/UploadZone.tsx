import React, { useCallback, useEffect, useRef, useState } from "react";
import { Upload, FileText, CheckCircle, BookOpen } from "lucide-react";
import { LegendData } from "../types";

interface Props {
  onUpload: (file: File) => void;
  uploading: boolean;
  uploadingFilename?: string;
  error: string | null;
  legend: LegendData | null;
  onLegendUpload: (file: File) => void;
  legendUploading: boolean;
  legendError: string | null;
}

export default function UploadZone({
  onUpload,
  uploading,
  uploadingFilename,
  error,
  legend,
  onLegendUpload,
  legendUploading,
  legendError,
}: Props) {
  const [dragOver, setDragOver] = useState(false);
  const drawingInputRef = useRef<HTMLInputElement>(null);
  const legendInputRef = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState(0);
  const [stage, setStage] = useState("");
  const [legendProgress, setLegendProgress] = useState(0);
  const [legendStage, setLegendStage] = useState("");
  const isPdf = uploadingFilename?.toLowerCase().endsWith(".pdf");

  // Drawing upload progress
  useEffect(() => {
    if (!uploading) {
      setProgress(0);
      setStage("");
      return;
    }
    setProgress(0);
    setStage("Reading file...");

    const stages = isPdf
      ? [
          { at: 8, label: "Uploading PDF drawing..." },
          { at: 18, label: "Splitting PDF pages..." },
          { at: 30, label: "Sending to AI vision model..." },
          { at: 45, label: "Scanning floor plan for device symbols..." },
          { at: 60, label: "Identifying fire alarm devices..." },
          { at: 75, label: "Counting devices per type..." },
          { at: 85, label: "Merging results across pages..." },
          { at: 93, label: "Finalizing device counts..." },
        ]
      : legend
      ? [
          { at: 8, label: "Uploading drawing file..." },
          { at: 18, label: "Converting to DXF format..." },
          { at: 30, label: "Scanning block definitions..." },
          { at: 42, label: "Detecting INSERT entities..." },
          { at: 52, label: "Classifying blocks using legend..." },
          { at: 65, label: "Matching symbols to legend definitions..." },
          { at: 78, label: "Consolidating symbol variants..." },
          { at: 88, label: "Counting devices and building summary..." },
          { at: 93, label: "Finalizing symbol table..." },
        ]
      : [
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
  }, [uploading, legend, isPdf]);

  // Legend upload progress
  useEffect(() => {
    if (!legendUploading) {
      setLegendProgress(0);
      setLegendStage("");
      return;
    }
    setLegendProgress(0);
    setLegendStage("Uploading legend file...");

    const stages = [
      { at: 8, label: "Uploading legend file..." },
      { at: 18, label: "Sending to AI vision model..." },
      { at: 30, label: "Scanning legend sections..." },
      { at: 42, label: "Extracting symbol definitions..." },
      { at: 55, label: "Reading device codes and names..." },
      { at: 65, label: "Classifying symbol shapes..." },
      { at: 75, label: "Verifying completeness..." },
      { at: 85, label: "Generating symbol icons..." },
      { at: 93, label: "Finalizing legend data..." },
    ];

    let p = 0;
    const interval = setInterval(() => {
      const remaining = 95 - p;
      const increment = Math.max(0.25, remaining * 0.03);
      p = Math.min(95, p + increment);
      setLegendProgress(p);

      const s = [...stages].reverse().find((s) => p >= s.at);
      if (s) setLegendStage(s.label);
    }, 200);

    return () => clearInterval(interval);
  }, [legendUploading]);

  const handleDrawingFile = useCallback(
    (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop();
      if (ext !== "dxf" && ext !== "dwg" && ext !== "pdf") {
        return;
      }
      onUpload(file);
    },
    [onUpload]
  );

  const handleLegendFile = useCallback(
    (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop();
      if (!["pdf", "png", "jpg", "jpeg", "gif", "webp"].includes(ext || "")) {
        return;
      }
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

      const ext = file.name.toLowerCase().split(".").pop();
      // Auto-detect: images = legend, DXF/DWG/PDF = drawing
      // PDF is treated as a drawing if a legend is already uploaded, otherwise as a legend
      if (ext === "pdf" && !legend) {
        handleLegendFile(file);
      } else if (ext === "pdf" && legend) {
        handleDrawingFile(file);
      } else if (["png", "jpg", "jpeg", "gif", "webp"].includes(ext || "")) {
        handleLegendFile(file);
      } else if (ext === "dxf" || ext === "dwg") {
        handleDrawingFile(file);
      }
    },
    [handleDrawingFile, handleLegendFile]
  );

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(true);
  };

  const handleDragLeave = () => setDragOver(false);

  const handleDrawingChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleDrawingFile(file);
    e.target.value = "";
  };

  const handleLegendChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) handleLegendFile(file);
    e.target.value = "";
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
      >
        {uploading ? (
          <div className="upload-spinner">
            <div className="spinner" />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>
              {isPdf ? "Analyzing PDF with AI vision..." : legend ? "Analyzing with legend..." : "Analyzing drawing..."}
            </p>
            <div className="preview-progress-bar" style={{ width: 240 }}>
              <div
                className="preview-progress-fill"
                style={{ width: `${progress}%` }}
              />
            </div>
            <p className="preview-progress-stage">{stage}</p>
            <p className="preview-progress-hint">Large drawings may take up to a minute</p>
          </div>
        ) : legendUploading ? (
          <div className="upload-spinner">
            <div className="spinner" />
            <p style={{ fontWeight: 500, marginBottom: 4 }}>
              Parsing legend with AI...
            </p>
            <div className="preview-progress-bar" style={{ width: 240 }}>
              <div
                className="preview-progress-fill"
                style={{ width: `${legendProgress}%` }}
              />
            </div>
            <p className="preview-progress-stage">{legendStage}</p>
            <p className="preview-progress-hint">Legend parsing may take up to 30 seconds</p>
          </div>
        ) : (
          <>
            <Upload className="upload-icon" />
            <h2 className="upload-title">Upload a Construction Drawing</h2>
            <p className="upload-subtitle">
              Drop your DXF, DWG, or PDF file here, or click to browse.
              <br />
              FireGPT will detect and count all fire alarm symbols.
            </p>

            {/* Legend upload section */}
            <div className="legend-section">
              {legend ? (
                <div className="legend-attached">
                  <CheckCircle size={14} />
                  <span>
                    Legend: <strong>{legend.filename}</strong> ({legend.total_symbols} symbols)
                  </span>
                </div>
              ) : (
                <button
                  className="legend-upload-btn"
                  onClick={(e) => {
                    e.stopPropagation();
                    legendInputRef.current?.click();
                  }}
                >
                  <BookOpen size={14} />
                  <span>Upload Legend Sheet</span>
                  <span className="legend-optional">(optional)</span>
                </button>
              )}
              {legendError && (
                <div className="legend-error">{legendError}</div>
              )}
            </div>

            {/* Drawing upload button */}
            <div className="upload-actions">
              <button
                className="drawing-upload-btn"
                onClick={(e) => {
                  e.stopPropagation();
                  drawingInputRef.current?.click();
                }}
              >
                <FileText size={16} />
                <span>Choose Drawing File</span>
              </button>
              <div className="upload-formats">
                <span className="format-badge">.DXF</span>
                <span className="format-badge">.DWG</span>
                <span className="format-badge">.PDF</span>
              </div>
            </div>
          </>
        )}
        {error && <div className="upload-error">{error}</div>}
        <input
          ref={drawingInputRef}
          type="file"
          accept=".dxf,.dwg,.pdf"
          onChange={handleDrawingChange}
          style={{ display: "none" }}
        />
        <input
          ref={legendInputRef}
          type="file"
          accept=".pdf,.png,.jpg,.jpeg,.gif,.webp"
          onChange={handleLegendChange}
          style={{ display: "none" }}
        />
      </div>
    </div>
  );
}
