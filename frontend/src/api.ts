import { DrawingData, DrawingPreview, ChatMessage, LegendData } from "./types";

const API_BASE = process.env.REACT_APP_API_URL || "";

export async function uploadLegend(file: File): Promise<LegendData> {
  const formData = new FormData();
  formData.append("file", file);

  console.log(`[FireGPT] Uploading legend: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB, type: ${file.type})`);

  let res: Response;
  try {
    res = await fetch(`${API_BASE}/api/upload-legend`, {
      method: "POST",
      body: formData,
    });
  } catch (networkErr) {
    console.error("[FireGPT] Legend upload network error:", networkErr);
    throw new Error(`Network error: ${networkErr instanceof Error ? networkErr.message : "Could not reach server"}`);
  }

  console.log(`[FireGPT] Legend upload response: ${res.status} ${res.statusText}`);

  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try {
      const errBody = await res.json();
      console.error("[FireGPT] Legend upload error response:", errBody);
      detail = errBody.detail || detail;
    } catch {
      const textBody = await res.text().catch(() => "");
      console.error("[FireGPT] Legend upload non-JSON error:", res.status, textBody.slice(0, 500));
      if (textBody) detail = `${detail}: ${textBody.slice(0, 200)}`;
    }
    throw new Error(detail);
  }

  const data = await res.json();
  console.log(`[FireGPT] Legend parsed successfully: ${data.total_symbols} symbols`, data);
  return data;
}

export async function uploadDrawing(file: File, legendId?: string): Promise<DrawingData> {
  const formData = new FormData();
  formData.append("file", file);

  const url = legendId
    ? `${API_BASE}/api/upload?legend_id=${encodeURIComponent(legendId)}`
    : `${API_BASE}/api/upload`;

  const res = await fetch(url, {
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
