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
  const maxDim = Math.max(vbW, vbH);
  const markerRadius = maxDim * 0.004;
  const selectedRadius = maxDim * 0.012;
  const strokeWidth = markerRadius * 0.35;
  const selectedStroke = selectedRadius * 0.25;
  const fontSize = selectedRadius * 1.2;

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

  // Debug: log coordinate info when symbol is selected
  if (selectedSymbol && preview) {
    const sym = symbols.find((s) => s.block_name === selectedSymbol);
    if (sym && sym.locations.length > 0) {
      const sample = sym.locations.slice(0, 3);
      console.log(`[DrawingViewer] viewBox="${preview.viewBox}", selectedRadius=${selectedRadius}`);
      console.log(`[DrawingViewer] ${sym.label}: ${sym.locations.length} locations, sample:`, sample.map(([x,y]) => `(${x}, ${-y})`));
    }
  }

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
              <defs>
                <filter id="marker-shadow" x="-50%" y="-50%" width="200%" height="200%">
                  <feDropShadow dx="0" dy="0" stdDeviation={maxDim * 0.002} floodColor="rgba(0,0,0,0.6)" />
                </filter>
              </defs>
              {/* Debug: center crosshair to verify overlay renders */}
              <circle
                cx={viewBoxParts[0] + vbW / 2}
                cy={viewBoxParts[1] + vbH / 2}
                r={maxDim * 0.02}
                fill="red"
                opacity={0.8}
                stroke="yellow"
                strokeWidth={maxDim * 0.005}
              />
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
                        filter="url(#marker-shadow)"
                      >
                        {/* Dark outline ring for contrast */}
                        <circle
                          cx={x}
                          cy={-y}
                          r={selectedRadius + selectedStroke}
                          fill="rgba(0,0,0,0.5)"
                        />
                        {/* Main colored circle */}
                        <circle
                          cx={x}
                          cy={-y}
                          r={selectedRadius}
                          fill={symbol.color}
                          stroke="white"
                          strokeWidth={selectedStroke}
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
                          stroke="rgba(0,0,0,0.4)"
                          strokeWidth={fontSize * 0.08}
                          paintOrder="stroke"
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
                      <g key={`${symbol.block_name}-${i}`}>
                        <circle
                          cx={x}
                          cy={-y}
                          r={r + strokeWidth}
                          fill="rgba(0,0,0,0.4)"
                        />
                        <circle
                          cx={x}
                          cy={-y}
                          r={r}
                          fill={symbol.color}
                          stroke="white"
                          strokeWidth={strokeWidth}
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
                      </g>
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
