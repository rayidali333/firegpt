export interface SymbolInfo {
  block_name: string;
  label: string;
  count: number;
  locations: [number, number][];
  color: string;
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
}
