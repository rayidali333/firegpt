import React, { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { ZoomIn, ZoomOut, Maximize2, Loader } from "lucide-react";
import { DrawingPreview, SymbolInfo } from "../types";

/**
 * Generates SVG polygon points for a regular n-sided shape centered at (cx, cy) with radius r.
 */
function polygonPoints(cx: number, cy: number, r: number, sides: number): string {
  return Array.from({ length: sides }, (_, i) => {
    const angle = (Math.PI * 2 / sides) * i - Math.PI / 2;
    return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
  }).join(" ");
}

/**
 * Renders a shape outline + code text for a symbol marker on the drawing view.
 * Uses the legend's shape_code (pentagon, hexagon, square, etc.) instead of plain circles.
 */
function DrawingMarkerShape({
  cx, cy, r, color, strokeW, code, shape, fontSize, isSelected,
}: {
  cx: number; cy: number; r: number; color: string; strokeW: number;
  code: string; shape: string; fontSize: number; isSelected?: boolean;
}) {
  const fill = isSelected ? color : color;
  const stroke = "white";
  const darkStroke = "rgba(0,0,0,0.5)";

  // Build the outer dark outline shape + colored fill shape
  let outerShape: React.ReactNode;
  let innerShape: React.ReactNode;
  const outerR = r + strokeW;

  switch (shape) {
    case "pentagon": {
      outerShape = <polygon points={polygonPoints(cx, cy, outerR, 5)} fill={darkStroke} />;
      innerShape = <polygon points={polygonPoints(cx, cy, r, 5)} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    case "hexagon": {
      outerShape = <polygon points={polygonPoints(cx, cy, outerR, 6)} fill={darkStroke} />;
      innerShape = <polygon points={polygonPoints(cx, cy, r, 6)} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    case "triangle": {
      outerShape = <polygon points={polygonPoints(cx, cy, outerR, 3)} fill={darkStroke} />;
      innerShape = <polygon points={polygonPoints(cx, cy, r, 3)} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    case "diamond": {
      outerShape = <polygon points={polygonPoints(cx, cy, outerR, 4)} fill={darkStroke} />;
      innerShape = <polygon points={polygonPoints(cx, cy, r, 4)} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    case "star": {
      const starPts = (rad: number) => Array.from({ length: 10 }, (_, i) => {
        const rr = i % 2 === 0 ? rad : rad * 0.5;
        const angle = (Math.PI / 5) * i - Math.PI / 2;
        return `${cx + rr * Math.cos(angle)},${cy + rr * Math.sin(angle)}`;
      }).join(" ");
      outerShape = <polygon points={starPts(outerR)} fill={darkStroke} />;
      innerShape = <polygon points={starPts(r)} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    case "square": {
      const half = r * 0.85; // slightly smaller to look proportional
      const outerHalf = outerR * 0.85;
      outerShape = <rect x={cx - outerHalf} y={cy - outerHalf} width={outerHalf * 2} height={outerHalf * 2} rx={strokeW} fill={darkStroke} />;
      innerShape = <rect x={cx - half} y={cy - half} width={half * 2} height={half * 2} rx={strokeW} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
    default: { // circle
      outerShape = <circle cx={cx} cy={cy} r={outerR} fill={darkStroke} />;
      innerShape = <circle cx={cx} cy={cy} r={r} fill={fill} stroke={stroke} strokeWidth={strokeW} />;
      break;
    }
  }

  return (
    <>
      {outerShape}
      {innerShape}
      {code && isSelected && (
        <text
          x={cx} y={cy}
          textAnchor="middle" dominantBaseline="central"
          fill="white" fontSize={fontSize} fontWeight="bold"
          fontFamily="Arial, sans-serif"
          stroke="rgba(0,0,0,0.4)" strokeWidth={fontSize * 0.08}
          paintOrder="stroke"
          style={{ pointerEvents: "none" }}
        >
          {code}
        </text>
      )}
    </>
  );
}

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

  // Parse viewBox for marker sizing
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

  // Build symbols with SVG-space positions from preview data
  const symbolsWithPositions = useMemo(() => {
    if (!preview?.symbol_positions) return [];
    return symbols
      .map((s) => ({
        ...s,
        svgPositions: (preview.symbol_positions[s.block_name] || []) as [number, number][],
      }))
      .filter((s) => s.svgPositions.length > 0);
  }, [symbols, preview]);

  // Simulated progress for loading state
  const [loadProgress, setLoadProgress] = useState(0);
  const [loadStage, setLoadStage] = useState("");

  useEffect(() => {
    if (!loading) {
      setLoadProgress(0);
      setLoadStage("");
      return;
    }
    setLoadProgress(0);
    setLoadStage("Reading DXF geometry...");

    const stages = [
      { at: 15, label: "Parsing lines and polylines..." },
      { at: 30, label: "Processing circles and arcs..." },
      { at: 45, label: "Rendering floor plan to SVG..." },
      { at: 60, label: "Scanning symbol positions..." },
      { at: 75, label: "Matching symbols to floor plan..." },
      { at: 85, label: "Applying coordinate transforms..." },
      { at: 92, label: "Generating marker overlay..." },
    ];

    let progress = 0;
    const interval = setInterval(() => {
      // Slow down as we approach 95% (never reaches 100 until actually done)
      const remaining = 95 - progress;
      const increment = Math.max(0.3, remaining * 0.04);
      progress = Math.min(95, progress + increment);
      setLoadProgress(progress);

      const stage = [...stages].reverse().find((s) => progress >= s.at);
      if (stage) setLoadStage(stage.label);
    }, 200);

    return () => clearInterval(interval);
  }, [loading]);

  if (loading) {
    return (
      <div className="drawing-viewer">
        <div className="drawing-viewer-loading">
          <Loader className="spin" />
          <p style={{ fontWeight: 500 }}>Generating drawing preview...</p>
          <div className="preview-progress-bar">
            <div
              className="preview-progress-fill"
              style={{ width: `${loadProgress}%` }}
            />
          </div>
          <p className="preview-progress-stage">{loadStage}</p>
          <p className="preview-progress-hint">
            Large drawings may take up to 3 minutes
          </p>
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

  // Legend items: symbols that have SVG positions
  const legendItems = symbolsWithPositions.slice(0, 12);

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
              {selectedSymbol ? (
                // Selected mode: show only the selected symbol with shape + number
                symbolsWithPositions
                  .filter((s) => s.block_name === selectedSymbol)
                  .map((symbol) =>
                    symbol.svgPositions.map(([cx, cy], i) => (
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
                        <DrawingMarkerShape
                          cx={cx} cy={cy} r={selectedRadius}
                          color={symbol.color}
                          strokeW={selectedStroke}
                          code={symbol.legend_code || String(i + 1)}
                          shape={symbol.shape_code || "circle"}
                          fontSize={fontSize}
                          isSelected
                        />
                        <title>
                          {symbol.label} #{i + 1}
                        </title>
                      </g>
                    ))
                  )
              ) : (
                // Default mode: show all symbols as small shaped markers
                symbolsWithPositions.map((symbol) =>
                  symbol.svgPositions.map(([cx, cy], i) => {
                    const isHovered = hoveredMarker === symbol.block_name;
                    const r = isHovered ? markerRadius * 1.5 : markerRadius;
                    return (
                      <g
                        key={`${symbol.block_name}-${i}`}
                        className="viewer-marker"
                        onMouseEnter={() => setHoveredMarker(symbol.block_name)}
                        onMouseLeave={() => setHoveredMarker(null)}
                        onClick={(e) => {
                          e.stopPropagation();
                          onSelectSymbol(symbol.block_name);
                        }}
                        style={{ cursor: "pointer" }}
                      >
                        <DrawingMarkerShape
                          cx={cx} cy={cy} r={r}
                          color={symbol.color}
                          strokeW={strokeWidth}
                          code=""
                          shape={symbol.shape_code || "circle"}
                          fontSize={0}
                        />
                        <title>
                          {symbol.label} ({symbol.count})
                        </title>
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
        const sym = symbolsWithPositions.find((s) => s.block_name === selectedSymbol);
        if (!sym) return null;
        return (
          <div className="viewer-selection-bar" style={{ backgroundColor: sym.color }}>
            <span>
              Showing <strong>{sym.svgPositions.length}</strong> {sym.label} locations
              {sym.svgPositions.length !== sym.count && (
                <> (of {sym.count} total — {sym.count - sym.svgPositions.length} without coordinates)</>
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
