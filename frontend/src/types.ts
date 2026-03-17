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
  legend_shape: string;
  svg_icon: string;
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
  type: "info" | "success" | "warning" | "error" | "detail" | "section";
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
  svg_icon: string;
}

export interface LegendData {
  legend_id: string;
  filename: string;
  symbols: LegendSymbol[];
  total_symbols: number;
  systems: string[];
}

export interface ProjectData {
  project_id: string;
  name: string;
  legend_id: string | null;
  drawing_ids: string[];
  created_at: string;
}

export interface ProjectDrawingInfo {
  drawing_id: string;
  filename: string;
  file_type: string;
  total_symbols: number;
  symbol_types: number;
}

export interface ProjectSummary {
  project_id: string;
  project_name: string;
  total_drawings: number;
  total_symbols: number;
  total_types: number;
  symbols: SymbolInfo[];
  per_sheet: Record<string, SymbolInfo[]>;
  drawings: ProjectDrawingInfo[];
}
