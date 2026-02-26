import { DrawingData } from "./types";

const API_BASE = process.env.REACT_APP_API_URL || "http://localhost:8000";

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

export async function chatWithDrawing(
  drawingId: string,
  message: string
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ drawing_id: drawingId, message }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Chat failed" }));
    throw new Error(err.detail || "Chat failed");
  }

  const data = await res.json();
  return data.response;
}
