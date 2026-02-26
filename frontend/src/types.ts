export interface SymbolInfo {
  block_name: string;
  label: string;
  count: number;
  sample_locations: [number, number][];
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
}
