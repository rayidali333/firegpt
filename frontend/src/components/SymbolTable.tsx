import React from "react";
import { MapPin } from "lucide-react";
import { SymbolInfo } from "../types";

interface Props {
  symbols: SymbolInfo[];
  total: number;
  selectedSymbol: string | null;
  onSelectSymbol: (blockName: string | null) => void;
}

export default function SymbolTable({
  symbols,
  total,
  selectedSymbol,
  onSelectSymbol,
}: Props) {
  return (
    <div className="symbol-table">
      <div className="symbol-table-header">
        <h3 className="symbol-table-title">Detected Symbols</h3>
        <span className="symbol-table-count">{total} total</span>
      </div>

      {/* Column headers */}
      <div className="symbol-table-columns">
        <span className="col-symbol">Symbol</span>
        <span className="col-locations">Locations</span>
        <span className="col-count">Count</span>
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
            return (
              <div
                key={s.block_name}
                className={`symbol-row ${isSelected ? "selected" : ""}`}
                onClick={() =>
                  onSelectSymbol(isSelected ? null : s.block_name)
                }
              >
                <div className="symbol-color-indicator">
                  <span
                    className="symbol-dot"
                    style={{ backgroundColor: s.color }}
                  />
                </div>
                <div className="symbol-info">
                  <span className="symbol-label">{s.label}</span>
                  <span className="symbol-block-name">{s.block_name}</span>
                </div>
                <div className="symbol-locations-count">
                  {s.locations.length > 0 && (
                    <span className="symbol-has-locations" title="Has location data">
                      <MapPin />
                    </span>
                  )}
                </div>
                <span className="symbol-count">{s.count}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
