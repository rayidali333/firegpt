import { DrawingData, DrawingPreview, ChatMessage, LegendData, LegendSymbol, ProjectData, ProjectSummary } from "./types";

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

  console.log(
    `[FireGPT] Uploading drawing: ${file.name} (${(file.size / 1024 / 1024).toFixed(2)} MB)` +
    (legendId ? `, with legend_id=${legendId}` : ", NO legend attached")
  );

  const url = legendId
    ? `${API_BASE}/api/upload?legend_id=${encodeURIComponent(legendId)}`
    : `${API_BASE}/api/upload`;

  let res: Response;
  try {
    res = await fetch(url, {
      method: "POST",
      body: formData,
    });
  } catch (networkErr) {
    console.error("[FireGPT] Drawing upload network error:", networkErr);
    throw new Error(`Network error: ${networkErr instanceof Error ? networkErr.message : "Could not reach server"}`);
  }

  console.log(`[FireGPT] Drawing upload response: ${res.status} ${res.statusText}`);

  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try {
      const errBody = await res.json();
      console.error("[FireGPT] Drawing upload error response:", errBody);
      detail = errBody.detail || detail;
    } catch {
      const textBody = await res.text().catch(() => "");
      console.error("[FireGPT] Drawing upload non-JSON error:", res.status, textBody.slice(0, 500));
      if (textBody) detail = `${detail}: ${textBody.slice(0, 200)}`;
    }
    throw new Error(detail);
  }

  const data = await res.json();
  console.log(
    `[FireGPT] Drawing parsed: ${data.symbols?.length} symbol types, ` +
    `${data.symbols?.reduce((sum: number, s: any) => sum + s.count, 0)} total devices`,
    data
  );
  return data;
}

export async function getDrawing(drawingId: string): Promise<DrawingData> {
  const res = await fetch(`${API_BASE}/api/drawings/${drawingId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Drawing not found" }));
    throw new Error(err.detail || "Drawing not found");
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

/**
 * Stream a chat response via SSE. Calls onChunk with each text fragment
 * as it arrives, enabling real-time incremental display.
 *
 * Falls back to non-streaming /api/chat if streaming fails.
 */
export async function chatWithDrawingStream(
  drawingId: string,
  message: string,
  history: ChatMessage[] = [],
  onChunk: (text: string) => void,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      drawing_id: drawingId,
      message,
      history: history.map((m) => ({ role: m.role, content: m.content })),
    }),
  });

  if (!res.ok) {
    // Fall back to non-streaming endpoint
    console.warn("[FireGPT] Streaming failed, falling back to non-streaming chat");
    return chatWithDrawing(drawingId, message, history);
  }

  const reader = res.body?.getReader();
  if (!reader) {
    return chatWithDrawing(drawingId, message, history);
  }

  const decoder = new TextDecoder();
  let fullText = "";
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });

    // Parse SSE events from buffer
    const lines = buffer.split("\n");
    // Keep the last potentially incomplete line in buffer
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const jsonStr = line.slice(6).trim();
      if (!jsonStr) continue;

      try {
        const event = JSON.parse(jsonStr);
        if (event.done) {
          return fullText;
        }
        if (event.error) {
          throw new Error(event.error);
        }
        if (event.text) {
          fullText += event.text;
          onChunk(event.text);
        }
      } catch (e) {
        // Ignore parse errors from incomplete chunks
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }

  return fullText;
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

// ── Legend CRUD ──

export async function updateLegendSymbol(
  legendId: string,
  symbolIdx: number,
  update: Partial<LegendSymbol>
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/legends/${legendId}/symbols/${symbolIdx}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(update),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Update failed" }));
    throw new Error(err.detail || "Update failed");
  }
}

export async function addLegendSymbol(
  legendId: string,
  symbol: LegendSymbol
): Promise<{ index: number }> {
  const res = await fetch(
    `${API_BASE}/api/legends/${legendId}/symbols`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(symbol),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Add failed" }));
    throw new Error(err.detail || "Add failed");
  }
  return res.json();
}

export async function deleteLegendSymbol(
  legendId: string,
  symbolIdx: number
): Promise<void> {
  const res = await fetch(
    `${API_BASE}/api/legends/${legendId}/symbols/${symbolIdx}`,
    { method: "DELETE" }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Delete failed" }));
    throw new Error(err.detail || "Delete failed");
  }
}

// ── Project API (Phase 4: Multi-Sheet & Batch Processing) ──

export async function createProject(
  name: string,
  legendId?: string
): Promise<ProjectData> {
  const params = new URLSearchParams({ name });
  if (legendId) params.set("legend_id", legendId);

  const res = await fetch(`${API_BASE}/api/projects?${params}`, {
    method: "POST",
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to create project" }));
    throw new Error(err.detail || "Failed to create project");
  }
  return res.json();
}

export async function getProject(projectId: string): Promise<ProjectData> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Project not found" }));
    throw new Error(err.detail || "Project not found");
  }
  return res.json();
}

export async function listProjects(): Promise<ProjectData[]> {
  const res = await fetch(`${API_BASE}/api/projects`);
  if (!res.ok) return [];
  return res.json();
}

export async function uploadDrawingToProject(
  projectId: string,
  file: File
): Promise<DrawingData> {
  const formData = new FormData();
  formData.append("file", file);

  console.log(`[FireGPT] Uploading drawing to project ${projectId}: ${file.name}`);

  const res = await fetch(`${API_BASE}/api/projects/${projectId}/upload-drawing`, {
    method: "POST",
    body: formData,
  });

  if (!res.ok) {
    let detail = `Server error ${res.status}`;
    try {
      const errBody = await res.json();
      detail = errBody.detail || detail;
    } catch {
      const textBody = await res.text().catch(() => "");
      if (textBody) detail = `${detail}: ${textBody.slice(0, 200)}`;
    }
    throw new Error(detail);
  }

  return res.json();
}

export async function getProjectSummary(projectId: string): Promise<ProjectSummary> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/summary`);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Summary failed" }));
    throw new Error(err.detail || "Summary failed");
  }
  return res.json();
}

export async function chatWithProjectStream(
  projectId: string,
  message: string,
  history: ChatMessage[] = [],
  activeDrawingId?: string,
  onChunk?: (text: string) => void,
): Promise<string> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/chat/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      project_id: projectId,
      message,
      history: history.map((m) => ({ role: m.role, content: m.content })),
      active_drawing_id: activeDrawingId || null,
    }),
  });

  if (!res.ok) {
    // Fall back to non-streaming
    const fallbackRes = await fetch(`${API_BASE}/api/projects/${projectId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        message,
        history: history.map((m) => ({ role: m.role, content: m.content })),
        active_drawing_id: activeDrawingId || null,
      }),
    });
    if (!fallbackRes.ok) throw new Error("Chat failed");
    const data = await fallbackRes.json();
    return data.response;
  }

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let fullText = "";
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      const jsonStr = line.slice(6).trim();
      if (!jsonStr) continue;

      try {
        const event = JSON.parse(jsonStr);
        if (event.done) return fullText;
        if (event.error) throw new Error(event.error);
        if (event.text) {
          fullText += event.text;
          onChunk?.(event.text);
        }
      } catch (e) {
        if (e instanceof SyntaxError) continue;
        throw e;
      }
    }
  }

  return fullText;
}
