import React, { useState } from "react";
import { MapPin, Download, Check, X, Edit2 } from "lucide-react";
import { SymbolInfo } from "../types";

function SymbolMarker({ color, code, shape }: { color: string; code: string; shape: string }) {
  if (!code) {
    return <span className="symbol-dot" style={{ backgroundColor: color }} />;
  }

  // Determine SVG size based on code length
  const isLong = code.length > 3;
  const w = isLong ? 38 : 26;
  const h = 22;
  const cx = w / 2;
  const cy = h / 2;
  const fontSize = isLong ? 7.5 : (code.length > 2 ? 8 : 9);

  // Build SVG shape path
  let shapePath: React.ReactNode;
  const stroke = color;
  const fill = "none";
  const sw = 1.5; // stroke width

  switch (shape) {
    case "pentagon": {
      const r = 9;
      const pts = Array.from({ length: 5 }, (_, i) => {
        const angle = (Math.PI * 2 / 5) * i - Math.PI / 2;
        return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
      }).join(" ");
      shapePath = <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
    case "hexagon": {
      const r = 9;
      const pts = Array.from({ length: 6 }, (_, i) => {
        const angle = (Math.PI / 3) * i - Math.PI / 2;
        return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
      }).join(" ");
      shapePath = <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
    case "triangle": {
      const pts = `${cx},${cy - 9} ${cx + 10},${cy + 7} ${cx - 10},${cy + 7}`;
      shapePath = <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
    case "diamond": {
      const pts = `${cx},${cy - 9} ${cx + 10},${cy} ${cx},${cy + 9} ${cx - 10},${cy}`;
      shapePath = <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
    case "star": {
      const outer = 9, inner = 4.5;
      const pts = Array.from({ length: 10 }, (_, i) => {
        const r = i % 2 === 0 ? outer : inner;
        const angle = (Math.PI / 5) * i - Math.PI / 2;
        return `${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`;
      }).join(" ");
      shapePath = <polygon points={pts} fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
    case "square": {
      const pad = isLong ? 2 : 3;
      shapePath = (
        <rect x={pad} y={cy - 9} width={w - pad * 2} height={18}
          rx="2" fill={fill} stroke={stroke} strokeWidth={sw} />
      );
      break;
    }
    default: { // circle
      const r = isLong ? Math.min(cx - 2, 10) : 9;
      shapePath = <ellipse cx={cx} cy={cy} rx={isLong ? cx - 2 : r} ry={r}
        fill={fill} stroke={stroke} strokeWidth={sw} />;
      break;
    }
  }

  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="symbol-marker-svg">
      {shapePath}
      <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
        fill={color} fontSize={fontSize} fontWeight="bold" fontFamily="Monaco, Menlo, monospace">
        {code}
      </text>
    </svg>
  );
}

interface Props {
  symbols: SymbolInfo[];
  total: number;
  selectedSymbol: string | null;
  onSelectSymbol: (blockName: string | null) => void;
  onOverride?: (blockName: string, label: string, count: number) => void;
  onExport?: () => void;
  xrefWarnings?: string[];
}

function shortBlockName(name: string): string {
  // For combined names like "A + B + C" or "A (+4 variants)", show first block only
  const first = name.split(" + ")[0].split(" (+")[0];
  // Strip long DXF path noise: take the meaningful prefix before numeric IDs and layer paths
  // e.g. "IT-DVC-DET-Detectors - SMOKE DETECTOR-3159778-FIRE ALARM..." → "IT-DVC-DET-Detectors"
  const parts = first.split(" - ");
  if (parts.length > 1) {
    return parts[0].trim();
  }
  // Truncate if still long
  return first.length > 40 ? first.slice(0, 37) + "..." : first;
}

const SOURCE_BADGE: Record<string, { label: string; className: string; title: string }> = {
  dictionary: { label: "Dict", className: "badge-high", title: "Matched via built-in dictionary — high confidence" },
  legend: { label: "Legend", className: "badge-legend", title: "Classified using uploaded legend sheet" },
  ai: { label: "AI", className: "badge-medium", title: "Classified by AI — verify if critical" },
  manual: { label: "Manual", className: "badge-manual", title: "Manually overridden by user" },
};

export default function SymbolTable({
  symbols,
  total,
  selectedSymbol,
  onSelectSymbol,
  onOverride,
  onExport,
  xrefWarnings,
}: Props) {
  const [editingBlock, setEditingBlock] = useState<string | null>(null);
  const [editLabel, setEditLabel] = useState("");
  const [editCount, setEditCount] = useState("");

  const startEdit = (s: SymbolInfo, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingBlock(s.block_name);
    setEditLabel(s.label);
    setEditCount(String(s.count));
  };

  const cancelEdit = (e: React.MouseEvent) => {
    e.stopPropagation();
    setEditingBlock(null);
  };

  const confirmEdit = (blockName: string, e: React.MouseEvent) => {
    e.stopPropagation();
    const count = parseInt(editCount, 10);
    if (!editLabel.trim() || isNaN(count) || count < 0) return;
    onOverride?.(blockName, editLabel.trim(), count);
    setEditingBlock(null);
  };

  return (
    <div className="symbol-table">
      <div className="symbol-table-header">
        <h3 className="symbol-table-title">Detected Symbols</h3>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span className="symbol-table-count">{total} total</span>
          {onExport && (
            <button
              className="export-btn"
              onClick={onExport}
              title="Export to CSV"
            >
              <Download size={14} />
              <span>CSV</span>
            </button>
          )}
        </div>
      </div>

      {xrefWarnings && xrefWarnings.length > 0 && (
        <div className="xref-warnings">
          {xrefWarnings.map((w, i) => (
            <div key={i} className="xref-warning-item">{w}</div>
          ))}
        </div>
      )}

      <div className="symbol-table-columns">
        <span className="col-symbol">Symbol</span>
        <span className="col-confidence">Source</span>
        <span className="col-locations">Loc</span>
        <span className="col-count">Count</span>
        <span className="col-edit"></span>
      </div>

      <div className="symbol-list">
        {symbols.length === 0 ? (
          <p
            style={{ color: "var(--text-muted)", fontSize: 12, padding: 8 }}
          >
            No symbols detected in this drawing.
          </p>
        ) : (
          symbols.map((s) => {
            const isSelected = selectedSymbol === s.block_name;
            const isEditing = editingBlock === s.block_name;
            const badge = SOURCE_BADGE[s.source] || SOURCE_BADGE.dictionary;
            return (
              <div
                key={s.block_name}
                className={`symbol-row ${isSelected ? "selected" : ""}`}
                onClick={() =>
                  !isEditing && onSelectSymbol(isSelected ? null : s.block_name)
                }
              >
                <div className="symbol-color-indicator">
                  <SymbolMarker color={s.color} code={s.legend_code || ""} shape={s.shape_code || "circle"} />
                </div>
                <div className="symbol-info">
                  {isEditing ? (
                    <input
                      className="edit-input edit-label-input"
                      value={editLabel}
                      onChange={(e) => setEditLabel(e.target.value)}
                      onClick={(e) => e.stopPropagation()}
                      autoFocus
                    />
                  ) : (
                    <span className="symbol-label">{s.label}</span>
                  )}
                  <span className="symbol-block-name" title={s.block_name}>
                    {shortBlockName(s.block_name)}
                    {s.block_variants && s.block_variants.length > 1 && (
                      <span className="variant-count" title={s.block_variants.map(v => shortBlockName(v)).join("\n")}>
                        {" "}({s.block_variants.length} variants)
                      </span>
                    )}
                  </span>
                </div>
                <div className="symbol-confidence">
                  <span className={`confidence-badge ${badge.className}`} title={badge.title}>
                    {badge.label}
                  </span>
                </div>
                <div className="symbol-locations-count">
                  {s.locations.length > 0 && (
                    <span className="symbol-has-locations" title="Has location data">
                      <MapPin size={12} />
                    </span>
                  )}
                </div>
                {isEditing ? (
                  <div className="edit-count-actions" onClick={(e) => e.stopPropagation()}>
                    <input
                      className="edit-input edit-count-input"
                      type="number"
                      min="0"
                      value={editCount}
                      onChange={(e) => setEditCount(e.target.value)}
                    />
                    <button className="edit-action-btn confirm" onClick={(e) => confirmEdit(s.block_name, e)} title="Save">
                      <Check size={12} />
                    </button>
                    <button className="edit-action-btn cancel" onClick={cancelEdit} title="Cancel">
                      <X size={12} />
                    </button>
                  </div>
                ) : (
                  <>
                    <span className="symbol-count">
                      {s.count}
                      {s.original_count !== null && s.original_count !== undefined && (
                        <span className="original-count" title={`Originally: ${s.original_count}`}>
                          ({s.original_count})
                        </span>
                      )}
                    </span>
                    {onOverride && (
                      <button
                        className="edit-row-btn"
                        onClick={(e) => startEdit(s, e)}
                        title="Edit count"
                      >
                        <Edit2 size={12} />
                      </button>
                    )}
                  </>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
