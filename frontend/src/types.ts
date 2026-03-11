export interface SymbolInfo {
  block_name: string;
  label: string;
  count: number;
  locations: [number, number][];
  color: string;
  confidence: "high" | "medium" | "manual";
  source: "dictionary" | "ai" | "legend" | "manual";
  block_variants: string[];
  original_count: number | null;
  shape_code: string;
  category: string;
  legend_code: string;
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

export interface DrawingPreview {
  svg: string;
  viewBox: string;
  width: number;
  height: number;
  symbol_positions: Record<string, [number, number][]>;
  position_debug: string[];
}

export interface LegendSymbol {
  code: string;
  name: string;
  category: string;
  shape: string;
  shape_code: string;
}

export interface LegendData {
  legend_id: string;
  filename: string;
  symbols: LegendSymbol[];
  total_symbols: number;
  systems: string[];
}
