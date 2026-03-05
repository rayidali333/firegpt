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
  const selectedRadius = Math.max(vbW, vbH) * 0.008;
  const strokeWidth = markerRadius * 0.35;
  const fontSize = selectedRadius * 1.4;

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
          <p style={{ fontSize: 11, color: "#888", marginTop: 4 }}>
            DWG files may not generate previews after conversion.
            For best results, export as DXF from AutoCAD.
          </p>
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
              {selectedSymbol ? (
                // Selected mode: show only the selected symbol with numbered circles
                symbols
                  .filter((s) => s.block_name === selectedSymbol)
                  .map((symbol) =>
                    symbol.locations.map(([x, y], i) => (
                      <g
                        key={`${symbol.block_name}-${i}`}
                        className="viewer-marker"
                        onMouseEnter={() => setHoveredMarker(`${symbol.block_name}-${i}`)}
                        onMouseLeave={() => setHoveredMarker(null)}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectSymbol(null);
                        }}
                        style={{ cursor: "pointer" }}
                      >
                        <circle
                          cx={x}
                          cy={-y}
                          r={selectedRadius}
                          fill={symbol.color}
                          stroke="white"
                          strokeWidth={strokeWidth * 1.5}
                          opacity={0.9}
                        />
                        <text
                          x={x}
                          y={-y}
                          textAnchor="middle"
                          dominantBaseline="central"
                          fill="white"
                          fontSize={fontSize}
                          fontWeight="bold"
                          fontFamily="Arial, sans-serif"
                          style={{ pointerEvents: "none" }}
                        >
                          {i + 1}
                        </text>
                        <title>
                          {symbol.label} #{i + 1}
                        </title>
                      </g>
                    ))
                  )
              ) : (
                // Default mode: show all symbols as small dots
                symbols.map((symbol) =>
                  symbol.locations.map(([x, y], i) => {
                    const isHovered = hoveredMarker === symbol.block_name;
                    const r = isHovered ? markerRadius * 1.5 : markerRadius;
                    return (
                      <circle
                        key={`${symbol.block_name}-${i}`}
                        cx={x}
                        cy={-y}
                        r={r}
                        fill={symbol.color}
                        stroke="white"
                        strokeWidth={strokeWidth}
                        opacity={0.75}
                        className="viewer-marker"
                        onMouseEnter={() =>
                          setHoveredMarker(symbol.block_name)
                        }
                        onMouseLeave={() => setHoveredMarker(null)}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectSymbol(symbol.block_name);
                        }}
                      >
                        <title>
                          {symbol.label} ({symbol.count})
                        </title>
                      </circle>
                    );
                  })
                )
              )}
            </svg>
          )}
        </div>
      </div>

      {/* Selected symbol info bar */}
      {selectedSymbol && showMarkers && (() => {
        const sym = symbols.find((s) => s.block_name === selectedSymbol);
        if (!sym) return null;
        return (
          <div className="viewer-selection-bar" style={{ backgroundColor: sym.color }}>
            <span>
              Showing <strong>{sym.locations.length}</strong> {sym.label} locations
              {sym.locations.length !== sym.count && (
                <> (of {sym.count} total — {sym.count - sym.locations.length} without coordinates)</>
              )}
            </span>
            <button onClick={() => onSelectSymbol(null)} className="viewer-selection-clear">
              Clear
            </button>
          </div>
        );
      })()}

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
