import React, { useState, useRef, useCallback } from "react";
import { ZoomIn, ZoomOut, Maximize2, Loader } from "lucide-react";
import { DrawingPreview, SymbolInfo } from "../types";

interface Props {
  preview: DrawingPreview | null;
  loading: boolean;
  symbols: SymbolInfo[];
  selectedSymbol: string | null;
  onSelectSymbol: (blockName: string | null) => void;
}

export default function DrawingViewer({
  preview,
  loading,
  symbols,
  selectedSymbol,
  onSelectSymbol,
}: Props) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const [dragStart, setDragStart] = useState({ x: 0, y: 0 });
  const [showMarkers, setShowMarkers] = useState(true);
  const [hoveredMarker, setHoveredMarker] = useState<string | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const handleWheel = useCallback(
    (e: React.WheelEvent) => {
      e.preventDefault();
      const delta = e.deltaY > 0 ? 0.9 : 1.1;
      setZoom((z) => Math.max(0.1, Math.min(20, z * delta)));
    },
    []
  );

  const handleMouseDown = useCallback(
    (e: React.MouseEvent) => {
      if (e.button !== 0) return;
      setDragging(true);
      setDragStart({ x: e.clientX - pan.x, y: e.clientY - pan.y });
    },
    [pan]
  );

  const handleMouseMove = useCallback(
    (e: React.MouseEvent) => {
      if (!dragging) return;
      setPan({
        x: e.clientX - dragStart.x,
        y: e.clientY - dragStart.y,
      });
    },
    [dragging, dragStart]
  );

  const handleMouseUp = useCallback(() => {
    setDragging(false);
  }, []);

  const resetView = useCallback(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }, []);

  const zoomIn = useCallback(() => {
    setZoom((z) => Math.min(20, z * 1.3));
  }, []);

  const zoomOut = useCallback(() => {
    setZoom((z) => Math.max(0.1, z / 1.3));
  }, []);

  // Parse viewBox for marker overlay
  const viewBoxParts = preview?.viewBox.split(" ").map(Number) || [
    0, 0, 100, 100,
  ];
  const [, , vbW, vbH] = viewBoxParts;
  const markerRadius = Math.max(vbW, vbH) * 0.005;
  const selectedRadius = markerRadius * 1.6;
  const strokeWidth = markerRadius * 0.35;

  if (loading) {
    return (
      <div className="drawing-viewer">
        <div className="drawing-viewer-loading">
          <Loader className="spin" />
          <p>Generating drawing preview...</p>
        </div>
      </div>
    );
  }

  if (!preview) {
    return (
      <div className="drawing-viewer">
        <div className="drawing-viewer-empty">
          <p>No preview available</p>
        </div>
      </div>
    );
  }

  // Build unique legend items from symbols that have locations
  const legendItems = symbols
    .filter((s) => s.locations.length > 0)
    .slice(0, 12);

  return (
    <div className="drawing-viewer">
      {/* Toolbar */}
      <div className="viewer-toolbar">
        <button className="viewer-tool-btn" onClick={zoomIn} title="Zoom In">
          <ZoomIn />
        </button>
        <button className="viewer-tool-btn" onClick={zoomOut} title="Zoom Out">
          <ZoomOut />
        </button>
        <button
          className="viewer-tool-btn"
          onClick={resetView}
          title="Reset View"
        >
          <Maximize2 />
        </button>
        <span className="viewer-zoom-level">{Math.round(zoom * 100)}%</span>
        <div className="viewer-toolbar-sep" />
        <label className="viewer-toggle">
          <input
            type="checkbox"
            checked={showMarkers}
            onChange={(e) => setShowMarkers(e.target.checked)}
          />
          <span>Symbols</span>
        </label>
      </div>

      {/* Canvas */}
      <div
        className="viewer-canvas-container"
        ref={containerRef}
        onWheel={handleWheel}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseUp}
        style={{ cursor: dragging ? "grabbing" : "grab" }}
      >
        <div
          className="viewer-canvas"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "center center",
          }}
        >
          {/* Floor plan SVG */}
          <div
            className="viewer-floor-plan"
            dangerouslySetInnerHTML={{ __html: preview.svg }}
          />

          {/* Interactive symbol marker overlay */}
          {showMarkers && (
            <svg
              className="viewer-marker-overlay"
              viewBox={preview.viewBox}
              preserveAspectRatio="xMidYMid meet"
            >
              {symbols.map((symbol) =>
                symbol.locations.map(([x, y], i) => {
                  const isSelected = selectedSymbol === symbol.block_name;
                  const isHovered = hoveredMarker === symbol.block_name;
                  const r = isSelected || isHovered ? selectedRadius : markerRadius;
                  return (
                    <circle
                      key={`${symbol.block_name}-${i}`}
                      cx={x}
                      cy={-y}
                      r={r}
                      fill={isSelected ? "#FFD700" : symbol.color}
                      stroke={isSelected ? "#B8860B" : "white"}
                      strokeWidth={strokeWidth}
                      opacity={
                        selectedSymbol && !isSelected ? 0.3 : 0.85
                      }
                      className="viewer-marker"
                      onMouseEnter={() =>
                        setHoveredMarker(symbol.block_name)
                      }
                      onMouseLeave={() => setHoveredMarker(null)}
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectSymbol(
                          isSelected ? null : symbol.block_name
                        );
                      }}
                    >
                      <title>
                        {symbol.label} ({symbol.block_name})
                      </title>
                    </circle>
                  );
                })
              )}
            </svg>
          )}
        </div>
      </div>

      {/* Legend */}
      {showMarkers && legendItems.length > 0 && (
        <div className="viewer-legend">
          {legendItems.map((s) => (
            <div
              key={s.block_name}
              className={`viewer-legend-item ${
                selectedSymbol === s.block_name ? "selected" : ""
              }`}
              onClick={() =>
                onSelectSymbol(
                  selectedSymbol === s.block_name ? null : s.block_name
                )
              }
            >
              <span
                className="viewer-legend-dot"
                style={{ backgroundColor: s.color }}
              />
              <span className="viewer-legend-label">{s.label}</span>
              <span className="viewer-legend-count">{s.count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
