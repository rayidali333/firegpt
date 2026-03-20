export interface SymbolInfo {
  block_name: string;
  label: string;
  count: number;
  locations: [number, number][];
  color: string;
  confidence: "high" | "medium" | "low" | "manual";
  source: "dictionary" | "ai" | "legend" | "manual";
  block_variants: string[];
  original_count: number | null;
  // Legend matching (Phase 1)
  matched_legend?: LegendDevice | null;
  match_confidence?: "high" | "medium" | "low" | null;
  original_label?: string | null;  // Pre-legend label (dictionary/AI guess)
  svg_icon?: string | null;  // Generated SVG icon markup (Phase 2)
}

export interface AuditEntry {
  block_name: string;
  label: string;
  count: number;
  method: string;
  confidence: string;
  matched_term: string | null;
  layers: string[];
}

export interface AnalysisStep {
  type: "info" | "success" | "warning" | "error";
  message: string;
}

export interface DrawingData {
  drawing_id: string;
  filename: string;
  file_type: string;
  symbols: SymbolInfo[];
  total_symbols: number;
  analysis: AnalysisStep[];
  audit: AuditEntry[];
  xref_warnings: string[];
  legend_texts: string[];
}

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  timestamp: number;
}

export interface LegendDevice {
  name: string;
  abbreviation: string | null;
  category: string;
  symbol_description: string;
  svg_icon?: string | null;
  color?: string | null;
}

export interface LegendData {
  legend_id: string;
  filename: string;
  devices: LegendDevice[];
  categories_found: string[];
  total_device_types: number;
  analysis: AnalysisStep[];
  notes: string;
}

export interface DrawingPreview {
  svg: string;
  viewBox: string;
  width: number;
  height: number;
  symbol_positions: Record<string, [number, number][]>;
  position_debug: string[];
}
