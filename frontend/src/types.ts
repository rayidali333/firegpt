export interface SymbolInfo {
  block_name: string;
  label: string;
  count: number;
  locations: [number, number][];
  color: string;
}

export interface DrawingData {
  drawing_id: string;
  filename: string;
  file_type: string;
  symbols: SymbolInfo[];
  total_symbols: number;
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
