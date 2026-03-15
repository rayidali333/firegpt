import React, { useState, useCallback } from "react";
import {
  Plus,
  Trash2,
  Check,
  X,
  RefreshCw,
  Pencil,
} from "lucide-react";
import { LegendData, LegendSymbol } from "../types";
import {
  updateLegendSymbol,
  addLegendSymbol,
  deleteLegendSymbol,
} from "../api";

interface Props {
  legend: LegendData;
  onLegendChange: (legend: LegendData) => void;
  onReAnalyze: () => void;
  reAnalyzing: boolean;
}

const EMPTY_SYMBOL: LegendSymbol = {
  code: "",
  name: "",
  category: "",
  shape: "",
  shape_code: "circle",
  svg_icon: "",
};

export default function LegendReview({
  legend,
  onLegendChange,
  onReAnalyze,
  reAnalyzing,
}: Props) {
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<Partial<LegendSymbol>>({});
  const [addingCategory, setAddingCategory] = useState<string | null>(null);
  const [addDraft, setAddDraft] = useState<LegendSymbol>({ ...EMPTY_SYMBOL });
  const [saving, setSaving] = useState(false);

  // Group symbols by category, preserving original indices
  const grouped: Record<string, { sym: LegendSymbol; idx: number }[]> = {};
  legend.symbols.forEach((sym, idx) => {
    const cat = sym.category || "Other";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push({ sym, idx });
  });
  const categories = Object.keys(grouped).sort();

  // ── Edit handlers ──
  const startEdit = useCallback((idx: number, sym: LegendSymbol) => {
    setEditingIdx(idx);
    setEditDraft({ code: sym.code, name: sym.name, category: sym.category });
  }, []);

  const cancelEdit = useCallback(() => {
    setEditingIdx(null);
    setEditDraft({});
  }, []);

  const saveEdit = useCallback(async () => {
    if (editingIdx === null) return;
    setSaving(true);
    try {
      await updateLegendSymbol(legend.legend_id, editingIdx, editDraft);
      // Update local state
      const updated = { ...legend };
      updated.symbols = [...legend.symbols];
      const sym = { ...updated.symbols[editingIdx] };
      if (editDraft.code !== undefined) sym.code = editDraft.code;
      if (editDraft.name !== undefined) sym.name = editDraft.name;
      if (editDraft.category !== undefined) sym.category = editDraft.category;
      updated.symbols[editingIdx] = sym;
      updated.systems = Array.from(new Set(updated.symbols.map((s) => s.category).filter(Boolean)));
      onLegendChange(updated);
      setEditingIdx(null);
      setEditDraft({});
    } catch (e: any) {
      console.error("Legend symbol update failed:", e);
    } finally {
      setSaving(false);
    }
  }, [editingIdx, editDraft, legend, onLegendChange]);

  // ── Add handlers ──
  const startAdd = useCallback((category: string) => {
    setAddingCategory(category);
    setAddDraft({ ...EMPTY_SYMBOL, category });
  }, []);

  const cancelAdd = useCallback(() => {
    setAddingCategory(null);
    setAddDraft({ ...EMPTY_SYMBOL });
  }, []);

  const saveAdd = useCallback(async () => {
    if (!addDraft.code.trim() || !addDraft.name.trim()) return;
    setSaving(true);
    try {
      await addLegendSymbol(legend.legend_id, addDraft);
      const updated = { ...legend };
      updated.symbols = [...legend.symbols, addDraft];
      updated.total_symbols = updated.symbols.length;
      updated.systems = Array.from(new Set(updated.symbols.map((s) => s.category).filter(Boolean)));
      onLegendChange(updated);
      setAddingCategory(null);
      setAddDraft({ ...EMPTY_SYMBOL });
    } catch (e: any) {
      console.error("Legend symbol add failed:", e);
    } finally {
      setSaving(false);
    }
  }, [addDraft, legend, onLegendChange]);

  // ── Delete handler ──
  const handleDelete = useCallback(
    async (idx: number) => {
      setSaving(true);
      try {
        await deleteLegendSymbol(legend.legend_id, idx);
        const updated = { ...legend };
        updated.symbols = legend.symbols.filter((_, i) => i !== idx);
        updated.total_symbols = updated.symbols.length;
        updated.systems = Array.from(new Set(updated.symbols.map((s) => s.category).filter(Boolean)));
        onLegendChange(updated);
        // Reset edit state if we were editing the deleted row
        if (editingIdx === idx) cancelEdit();
      } catch (e: any) {
        console.error("Legend symbol delete failed:", e);
      } finally {
        setSaving(false);
      }
    },
    [legend, onLegendChange, editingIdx, cancelEdit]
  );

  const renderSvgIcon = (svg: string) => {
    if (!svg) return <span className="legend-no-icon">-</span>;
    return (
      <span
        className="legend-svg-icon"
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    );
  };

  return (
    <div className="legend-review">
      <div className="legend-review-header">
        <div className="legend-review-title">
          <h3>Legend Review</h3>
          <span className="legend-review-count">
            {legend.total_symbols} symbols
          </span>
        </div>
        <div className="legend-review-actions">
          <button
            className="legend-reanalyze-btn"
            onClick={onReAnalyze}
            disabled={reAnalyzing || saving}
          >
            <RefreshCw className={reAnalyzing ? "spin" : ""} />
            {reAnalyzing ? "Analyzing..." : "Re-analyze"}
          </button>
        </div>
      </div>

      <div className="legend-review-body">
        {categories.map((category) => (
          <div key={category} className="legend-category-group">
            <div className="legend-category-header">
              <span className="legend-category-name">{category}</span>
              <span className="legend-category-count">
                {grouped[category].length}
              </span>
              <button
                className="legend-add-btn"
                onClick={() => startAdd(category)}
                disabled={saving || addingCategory !== null}
                title="Add symbol"
              >
                <Plus size={14} />
              </button>
            </div>

            <table className="legend-table">
              <thead>
                <tr>
                  <th className="legend-col-icon">Icon</th>
                  <th className="legend-col-code">Code</th>
                  <th className="legend-col-name">Name</th>
                  <th className="legend-col-shape">Shape</th>
                  <th className="legend-col-actions"></th>
                </tr>
              </thead>
              <tbody>
                {grouped[category].map(({ sym, idx }) => (
                  <tr
                    key={idx}
                    className={`legend-row ${editingIdx === idx ? "editing" : ""}`}
                  >
                    <td className="legend-col-icon">
                      {renderSvgIcon(sym.svg_icon)}
                    </td>

                    {editingIdx === idx ? (
                      <>
                        <td className="legend-col-code">
                          <input
                            className="legend-edit-input"
                            value={editDraft.code ?? sym.code}
                            onChange={(e) =>
                              setEditDraft((d) => ({ ...d, code: e.target.value }))
                            }
                            autoFocus
                          />
                        </td>
                        <td className="legend-col-name">
                          <input
                            className="legend-edit-input legend-edit-name"
                            value={editDraft.name ?? sym.name}
                            onChange={(e) =>
                              setEditDraft((d) => ({ ...d, name: e.target.value }))
                            }
                          />
                        </td>
                        <td className="legend-col-shape">
                          {sym.shape_code || sym.shape || "-"}
                        </td>
                        <td className="legend-col-actions">
                          <button
                            className="legend-action-btn confirm"
                            onClick={saveEdit}
                            disabled={saving}
                            title="Save"
                          >
                            <Check size={14} />
                          </button>
                          <button
                            className="legend-action-btn cancel"
                            onClick={cancelEdit}
                            title="Cancel"
                          >
                            <X size={14} />
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td className="legend-col-code">
                          <span className="legend-code">{sym.code}</span>
                        </td>
                        <td className="legend-col-name">{sym.name}</td>
                        <td className="legend-col-shape">
                          {sym.shape_code || sym.shape || "-"}
                        </td>
                        <td className="legend-col-actions">
                          <button
                            className="legend-action-btn edit"
                            onClick={() => startEdit(idx, sym)}
                            disabled={saving || editingIdx !== null}
                            title="Edit"
                          >
                            <Pencil size={14} />
                          </button>
                          <button
                            className="legend-action-btn delete"
                            onClick={() => handleDelete(idx)}
                            disabled={saving}
                            title="Delete"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                ))}

                {/* Add row (inline) */}
                {addingCategory === category && (
                  <tr className="legend-row adding">
                    <td className="legend-col-icon">
                      <span className="legend-no-icon">+</span>
                    </td>
                    <td className="legend-col-code">
                      <input
                        className="legend-edit-input"
                        placeholder="Code"
                        value={addDraft.code}
                        onChange={(e) =>
                          setAddDraft((d) => ({ ...d, code: e.target.value }))
                        }
                        autoFocus
                      />
                    </td>
                    <td className="legend-col-name">
                      <input
                        className="legend-edit-input legend-edit-name"
                        placeholder="Device name"
                        value={addDraft.name}
                        onChange={(e) =>
                          setAddDraft((d) => ({ ...d, name: e.target.value }))
                        }
                      />
                    </td>
                    <td className="legend-col-shape">
                      <select
                        className="legend-edit-input"
                        value={addDraft.shape_code}
                        onChange={(e) =>
                          setAddDraft((d) => ({ ...d, shape_code: e.target.value }))
                        }
                      >
                        <option value="circle">Circle</option>
                        <option value="square">Square</option>
                        <option value="diamond">Diamond</option>
                        <option value="hexagon">Hexagon</option>
                        <option value="pentagon">Pentagon</option>
                        <option value="triangle">Triangle</option>
                        <option value="star">Star</option>
                      </select>
                    </td>
                    <td className="legend-col-actions">
                      <button
                        className="legend-action-btn confirm"
                        onClick={saveAdd}
                        disabled={saving || !addDraft.code.trim() || !addDraft.name.trim()}
                        title="Add"
                      >
                        <Check size={14} />
                      </button>
                      <button
                        className="legend-action-btn cancel"
                        onClick={cancelAdd}
                        title="Cancel"
                      >
                        <X size={14} />
                      </button>
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        ))}
      </div>
    </div>
  );
}
