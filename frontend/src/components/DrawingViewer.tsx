import React, { useState, useRef, useCallback, useMemo, useEffect } from "react";
import { ZoomIn, ZoomOut, Maximize2, Loader } from "lucide-react";
import { DrawingPreview, SymbolInfo } from "../types";

interface Props {
  preview: DrawingPreview | null;
  loading: boolean;
  symbols: SymbolInfo[];
  selectedSymbol: string | null;
  onSelectSymbol: (blockName: string | null) => void;
}

/**
 * Extract inner content and viewBox from an SVG string for use in <symbol>.
 * Input:  '<svg viewBox="0 0 24 24"><circle .../></svg>'
 * Output: { viewBox: "0 0 24 24", inner: "<circle .../>" }
 */
function parseSvgIcon(svgStr: string): { viewBox: string; inner: string } | null {
  if (!svgStr) return null;
  // Extract viewBox
  const vbMatch = svgStr.match(/viewBox="([^"]*)"/);
  const viewBox = vbMatch ? vbMatch[1] : "0 0 24 24";
  // Extract inner content between <svg ...> and </svg>
  const innerMatch = svgStr.match(/<svg[^>]*>([\s\S]*)<\/svg>/i);
  if (!innerMatch) return null;
  return { viewBox, inner: innerMatch[1].trim() };
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
  // Icon sizes derived from marker radii
  const iconSize = markerRadius * 3;
  const selectedIconSize = selectedRadius * 2.2;

  // Build symbols with SVG-space positions from preview data.
  // Only show legend-matched symbols — unmatched raw blocks (Grid, cable fittings,
  // furniture etc.) are noise and shouldn't clutter the floor plan.
  const symbolsWithPositions = useMemo(() => {
    if (!preview?.symbol_positions) return [];
    return symbols
      .filter((s) => s.source === "legend")
      .map((s) => ({
        ...s,
        svgPositions: (preview.symbol_positions[s.block_name] || []) as [number, number][],
      }))
      .filter((s) => s.svgPositions.length > 0);
  }, [symbols, preview]);

  // Build icon symbol definitions: label → parsed SVG data
  const iconDefs = useMemo(() => {
    const defs: Record<string, { id: string; viewBox: string; inner: string }> = {};
    for (const sym of symbols) {
      if (!sym.svg_icon) continue;
      const parsed = parseSvgIcon(sym.svg_icon);
      if (!parsed) continue;
      // Use label as key (unique per consolidated symbol row)
      const id = `icon-${sym.block_name.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
      if (!defs[sym.block_name]) {
        defs[sym.block_name] = { id, ...parsed };
      }
    }
    return defs;
  }, [symbols]);

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

  // Helper: render an icon or fallback circle at position
  const renderDefaultMarker = (
    symbol: (typeof symbolsWithPositions)[0],
    cx: number,
    cy: number,
    i: number,
  ) => {
    const def = iconDefs[symbol.block_name];
    const isHovered = hoveredMarker === symbol.block_name;

    if (def) {
      // SVG icon marker
      const size = isHovered ? iconSize * 1.3 : iconSize;
      return (
        <g
          key={`${symbol.block_name}-${i}`}
          className="viewer-marker viewer-icon-marker"
          onMouseEnter={() => setHoveredMarker(symbol.block_name)}
          onMouseLeave={() => setHoveredMarker(null)}
          onClick={(e) => {
            e.stopPropagation();
            onSelectSymbol(symbol.block_name);
          }}
          style={{ color: symbol.color }}
        >
          {/* Background disc for visibility */}
          <circle
            cx={cx}
            cy={cy}
            r={size * 0.6}
            fill="white"
            stroke={symbol.color}
            strokeWidth={size * 0.08}
            opacity={0.92}
          />
          {/* Icon via <use> */}
          <use
            href={`#${def.id}`}
            x={cx - size / 2}
            y={cy - size / 2}
            width={size}
            height={size}
          />
          <title>
            {symbol.label} ({symbol.count})
          </title>
        </g>
      );
    }

    // Fallback: colored circle (no icon available)
    const r = isHovered ? markerRadius * 1.5 : markerRadius;
    return (
      <g key={`${symbol.block_name}-${i}`}>
        <circle
          cx={cx}
          cy={cy}
          r={r + strokeWidth}
          fill="rgba(0,0,0,0.4)"
        />
        <circle
          cx={cx}
          cy={cy}
          r={r}
          fill={symbol.color}
          stroke="white"
          strokeWidth={strokeWidth}
          className="viewer-marker"
          onMouseEnter={() => setHoveredMarker(symbol.block_name)}
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
  };

  // Helper: render a selected-mode icon or fallback numbered circle
  const renderSelectedMarker = (
    symbol: (typeof symbolsWithPositions)[0],
    cx: number,
    cy: number,
    i: number,
  ) => {
    const def = iconDefs[symbol.block_name];

    if (def) {
      // SVG icon with numbered overlay
      const size = selectedIconSize;
      return (
        <g
          key={`${symbol.block_name}-${i}`}
          className="viewer-marker viewer-icon-marker"
          onMouseEnter={() => setHoveredMarker(`${symbol.block_name}-${i}`)}
          onMouseLeave={() => setHoveredMarker(null)}
          onClick={(e) => {
            e.stopPropagation();
            onSelectSymbol(null);
          }}
          style={{ cursor: "pointer", color: symbol.color }}
          filter="url(#marker-shadow)"
        >
          {/* White background disc */}
          <circle
            cx={cx}
            cy={cy}
            r={size * 0.6}
            fill="white"
            stroke={symbol.color}
            strokeWidth={size * 0.1}
          />
          {/* Icon */}
          <use
            href={`#${def.id}`}
            x={cx - size / 2}
            y={cy - size / 2}
            width={size}
            height={size}
          />
          {/* Number badge */}
          <circle
            cx={cx + size * 0.4}
            cy={cy - size * 0.4}
            r={fontSize * 0.65}
            fill={symbol.color}
            stroke="white"
            strokeWidth={fontSize * 0.1}
          />
          <text
            x={cx + size * 0.4}
            y={cy - size * 0.4}
            textAnchor="middle"
            dominantBaseline="central"
            fill="white"
            fontSize={fontSize * 0.8}
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
      );
    }

    // Fallback: numbered colored circle
    return (
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
        <circle
          cx={cx}
          cy={cy}
          r={selectedRadius + selectedStroke}
          fill="rgba(0,0,0,0.5)"
        />
        <circle
          cx={cx}
          cy={cy}
          r={selectedRadius}
          fill={symbol.color}
          stroke="white"
          strokeWidth={selectedStroke}
        />
        <text
          x={cx}
          y={cy}
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
    );
  };

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
                {/* SVG icon symbol definitions */}
                {Object.values(iconDefs).map((def) => (
                  <symbol
                    key={def.id}
                    id={def.id}
                    viewBox={def.viewBox}
                    dangerouslySetInnerHTML={{ __html: def.inner }}
                  />
                ))}
              </defs>
              {selectedSymbol ? (
                // Selected mode: show only the selected symbol with icons or numbered circles
                symbolsWithPositions
                  .filter((s) => s.block_name === selectedSymbol)
                  .map((symbol) =>
                    symbol.svgPositions.map(([cx, cy], i) =>
                      renderSelectedMarker(symbol, cx, cy, i)
                    )
                  )
              ) : (
                // Default mode: show all symbols as icons or small dots
                symbolsWithPositions.map((symbol) =>
                  symbol.svgPositions.map(([cx, cy], i) =>
                    renderDefaultMarker(symbol, cx, cy, i)
                  )
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
          {legendItems.map((s) => {
            const def = iconDefs[s.block_name];
            return (
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
                {def ? (
                  <span
                    className="viewer-legend-icon"
                    style={{ color: s.color }}
                    dangerouslySetInnerHTML={{ __html: s.svg_icon || "" }}
                  />
                ) : (
                  <span
                    className="viewer-legend-dot"
                    style={{ backgroundColor: s.color }}
                  />
                )}
                <span className="viewer-legend-label">{s.label}</span>
                <span className="viewer-legend-count">{s.count}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
