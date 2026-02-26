import React from "react";
import { SymbolInfo } from "../types";

interface Props {
  symbols: SymbolInfo[];
  total: number;
}

export default function SymbolTable({ symbols, total }: Props) {
  return (
    <div className="symbol-table">
      <div className="symbol-table-header">
        <h3 className="symbol-table-title">Detected Symbols</h3>
        <span className="symbol-table-count">{total} total</span>
      </div>
      <div className="symbol-list">
        {symbols.length === 0 ? (
          <p style={{ color: "var(--text-muted)", fontSize: 13, padding: 12 }}>
            No symbols detected in this drawing.
          </p>
        ) : (
          symbols.map((s) => (
            <div key={s.block_name} className="symbol-row">
              <div className="symbol-info">
                <span className="symbol-label">{s.label}</span>
                <span className="symbol-block-name">{s.block_name}</span>
              </div>
              <span className="symbol-count">{s.count}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
