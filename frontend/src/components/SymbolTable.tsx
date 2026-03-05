import React, { useState } from "react";
import { MapPin, Download, Check, X, Edit2 } from "lucide-react";
import { SymbolInfo } from "../types";

interface Props {
  symbols: SymbolInfo[];
  total: number;
  selectedSymbol: string | null;
  onSelectSymbol: (blockName: string | null) => void;
  onOverride?: (blockName: string, label: string, count: number) => void;
  onExport?: () => void;
  xrefWarnings?: string[];
}

const CONFIDENCE_BADGE: Record<string, { label: string; className: string; title: string }> = {
  high: { label: "Dict", className: "badge-high", title: "Matched via dictionary — high confidence" },
  medium: { label: "AI", className: "badge-medium", title: "Classified by AI — verify if critical" },
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
            const badge = CONFIDENCE_BADGE[s.confidence] || CONFIDENCE_BADGE.high;
            return (
              <div
                key={s.block_name}
                className={`symbol-row ${isSelected ? "selected" : ""}`}
                onClick={() =>
                  !isEditing && onSelectSymbol(isSelected ? null : s.block_name)
                }
              >
                <div className="symbol-color-indicator">
                  <span
                    className="symbol-dot"
                    style={{ backgroundColor: s.color }}
                  />
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
                  <span className="symbol-block-name">
                    {s.block_name}
                    {s.block_variants && s.block_variants.length > 1 && (
                      <span className="variant-count" title={s.block_variants.join(", ")}>
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
