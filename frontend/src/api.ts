import { DrawingData, DrawingPreview, ChatMessage, LegendData, SymbolInfo } from "./types";

const API_BASE = process.env.REACT_APP_API_URL || "";

export async function uploadDrawing(file: File): Promise<DrawingData> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Upload failed" }));
    throw new Error(err.detail || "Upload failed");
  }

  return res.json();
}

export async function getDrawingPreview(
  drawingId: string
): Promise<DrawingPreview> {
  const res = await fetch(`${API_BASE}/api/drawings/${drawingId}/preview`);

  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Preview generation failed" }));
    throw new Error(err.detail || "Preview generation failed");
  }

  return res.json();
}

export async function chatWithDrawing(
  drawingId: string,
  message: string,
  history: ChatMessage[] = []
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      drawing_id: drawingId,
      message,
      history: history.map((m) => ({ role: m.role, content: m.content })),
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Chat failed" }));
    throw new Error(err.detail || "Chat failed");
  }

  const data = await res.json();
  return data.response;
}

export async function overrideSymbol(
  drawingId: string,
  blockName: string,
  label: string,
  count: number
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/drawings/${drawingId}/symbols/${encodeURIComponent(blockName)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label, count }),
    }
  );

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Override failed" }));
    throw new Error(err.detail || "Override failed");
  }
}

export function getExportUrl(drawingId: string): string {
  return `${API_BASE}/api/drawings/${drawingId}/export`;
}

export interface MatchLegendResult {
  status: string;
  matched: number;
  total_symbols: number;
  unmatched: number;
  symbols: SymbolInfo[];
}

export async function matchLegend(
  drawingId: string,
  legendId: string
): Promise<MatchLegendResult> {
  const res = await fetch(
    `${API_BASE}/api/drawings/${drawingId}/match-legend`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ legend_id: legendId }),
    }
  );

  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Legend matching failed" }));
    throw new Error(err.detail || "Legend matching failed");
  }

  return res.json();
}

export interface GenerateIconsResult {
  status: string;
  generated: number;
  total: number;
  failed: number;
  symbols: SymbolInfo[];
}

export async function generateIcons(
  drawingId: string
): Promise<GenerateIconsResult> {
  const res = await fetch(
    `${API_BASE}/api/drawings/${drawingId}/generate-icons`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    }
  );

  if (!res.ok) {
    const err = await res
      .json()
      .catch(() => ({ detail: "Icon generation failed" }));
    throw new Error(err.detail || "Icon generation failed");
  }

  return res.json();
}

export async function uploadLegend(file: File): Promise<LegendData> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch(`${API_BASE}/api/legend/upload`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Legend upload failed" }));
    throw new Error(err.detail || "Legend upload failed");
  }

  return res.json();
}
