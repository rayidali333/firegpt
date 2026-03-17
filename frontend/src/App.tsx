import React, { useState, useCallback, useEffect } from "react";
import { DrawingData, DrawingPreview, ChatMessage, LegendData, ProjectData } from "./types";
import {
  uploadDrawing, uploadLegend, getDrawingPreview, chatWithDrawingStream,
  overrideSymbol, getExportUrl, createProject, uploadDrawingToProject,
  chatWithProjectStream, getDrawing,
} from "./api";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import UploadZone from "./components/UploadZone";
import SymbolTable from "./components/SymbolTable";
import DrawingViewer from "./components/DrawingViewer";
import AnalysisLog from "./components/AnalysisLog";
import LegendReview from "./components/LegendReview";
import ChatPanel from "./components/ChatPanel";
import "./App.css";

function App() {
  const [drawing, setDrawing] = useState<DrawingData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"symbols" | "drawing" | "analysis" | "legend">("symbols");
  const [preview, setPreview] = useState<DrawingPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [chatSending, setChatSending] = useState(false);
  const [legend, setLegend] = useState<LegendData | null>(null);
  const [legendUploading, setLegendUploading] = useState(false);
  const [legendError, setLegendError] = useState<string | null>(null);

  // Project / multi-sheet state
  const [project, setProject] = useState<ProjectData | null>(null);
  const [projectDrawings, setProjectDrawings] = useState<Map<string, DrawingData>>(new Map());

  // Load preview when drawing changes
  useEffect(() => {
    if (!drawing) {
      setPreview(null);
      return;
    }
    setPreviewLoading(true);
    getDrawingPreview(drawing.drawing_id)
      .then((p) => {
        console.log("[FireGPT] Preview loaded. symbol_positions keys:", Object.keys(p.symbol_positions || {}));
        console.log("[FireGPT] Position counts:", Object.fromEntries(
          Object.entries(p.symbol_positions || {}).map(([k, v]) => [k, (v as any[]).length])
        ));
        if (p.position_debug?.length) {
          console.log("[FireGPT] Position debug:");
          p.position_debug.forEach((line: string) => console.log("  ", line));
        }
        setPreview(p);
      })
      .catch((e) => {
        console.warn("Preview generation failed:", e);
        setPreview(null);
      })
      .finally(() => setPreviewLoading(false));
  }, [drawing]);

  const handleLegendUpload = async (file: File) => {
    setLegendUploading(true);
    setLegendError(null);
    try {
      const data = await uploadLegend(file);
      setLegend(data);
    } catch (e: any) {
      const errorMsg = e.message || "Legend upload failed";
      console.error("[FireGPT] Legend upload failed:", errorMsg, e);
      setLegendError(errorMsg);
    } finally {
      setLegendUploading(false);
    }
  };

  const handleLegendReAnalyze = useCallback(async () => {
    if (!legend) return;
    // Re-fetch the original legend file is not possible (in-memory),
    // so we show a message directing user to re-upload
    // For now, reset the legend and let user re-upload
    setLegend(null);
    setLegendError(null);
    setActiveTab("symbols");
  }, [legend]);

  const handleLegendChange = useCallback((updated: LegendData) => {
    setLegend(updated);
  }, []);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      let data: DrawingData;

      if (project) {
        // Already in project mode — add drawing to existing project
        data = await uploadDrawingToProject(project.project_id, file);
        setProject((prev) =>
          prev ? { ...prev, drawing_ids: [...prev.drawing_ids, data.drawing_id] } : prev
        );
        setProjectDrawings((prev) => new Map(prev).set(data.drawing_id, data));
      } else if (drawing) {
        // Second drawing uploaded — auto-create a project
        const proj = await createProject(
          "Untitled Project",
          legend?.legend_id || undefined
        );
        // Add the existing first drawing to the project
        proj.drawing_ids.push(drawing.drawing_id);
        // Upload new drawing to the project
        data = await uploadDrawingToProject(proj.project_id, file);
        proj.drawing_ids.push(data.drawing_id);
        setProject(proj);
        setProjectDrawings(
          new Map([
            [drawing.drawing_id, drawing],
            [data.drawing_id, data],
          ])
        );
      } else {
        // First drawing — single-drawing mode
        data = await uploadDrawing(file, legend?.legend_id);
      }

      setDrawing(data);
      setMessages([]);
      setActiveTab("symbols");
      setSelectedSymbol(null);
      setPreview(null);
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleChat = async (message: string) => {
    if (!drawing) return;

    const userMsg: ChatMessage = {
      role: "user",
      content: message,
      timestamp: Date.now(),
    };
    const assistantMsg: ChatMessage = {
      role: "assistant",
      content: "",
      timestamp: Date.now(),
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setChatSending(true);

    const onChunk = (chunk: string) => {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === "assistant") {
          updated[updated.length - 1] = {
            ...last,
            content: last.content + chunk,
          };
        }
        return updated;
      });
    };

    try {
      if (project) {
        // Project mode — use project-wide chat with all sheets' context
        await chatWithProjectStream(
          project.project_id,
          message,
          messages,
          drawing.drawing_id,
          onChunk,
        );
      } else {
        // Single-drawing mode
        await chatWithDrawingStream(
          drawing.drawing_id,
          message,
          messages,
          onChunk,
        );
      }
    } catch (e: any) {
      setMessages((prev) => {
        const updated = [...prev];
        const last = updated[updated.length - 1];
        if (last && last.role === "assistant") {
          updated[updated.length - 1] = {
            ...last,
            content: `Error: ${e.message || "Failed to get response"}`,
          };
        }
        return updated;
      });
    } finally {
      setChatSending(false);
    }
  };

  const handleReset = () => {
    setDrawing(null);
    setMessages([]);
    setError(null);
    setActiveTab("symbols");
    setPreview(null);
    setSelectedSymbol(null);
    setLegend(null);
    setLegendError(null);
    setProject(null);
    setProjectDrawings(new Map());
  };

  const handleSelectSheet = useCallback(async (drawingId: string) => {
    // Switch to a different sheet in the project
    let d = projectDrawings.get(drawingId);
    if (!d) {
      try {
        d = await getDrawing(drawingId);
        setProjectDrawings((prev) => new Map(prev).set(drawingId, d!));
      } catch {
        return;
      }
    }
    setDrawing(d);
    setPreview(null);
    setSelectedSymbol(null);
    setActiveTab("symbols");
  }, [projectDrawings]);

  const handleSelectSymbol = useCallback(
    (blockName: string | null) => {
      setSelectedSymbol(blockName);
    },
    []
  );

  const handleOverride = useCallback(
    async (blockName: string, label: string, count: number) => {
      if (!drawing) return;
      try {
        await overrideSymbol(drawing.drawing_id, blockName, label, count);
        setDrawing((prev) => {
          if (!prev) return prev;
          const updated = {
            ...prev,
            symbols: prev.symbols.map((s) =>
              s.block_name === blockName
                ? {
                    ...s,
                    label,
                    count,
                    confidence: "manual" as const,
                    source: "manual" as const,
                    original_count: s.original_count ?? s.count,
                  }
                : s
            ),
          };
          updated.total_symbols = updated.symbols.reduce((sum, s) => sum + s.count, 0);
          return updated;
        });
      } catch (e: any) {
        console.error("Override failed:", e);
      }
    },
    [drawing]
  );

  const handleExport = useCallback(() => {
    if (!drawing) return;
    window.open(getExportUrl(drawing.drawing_id), "_blank");
  }, [drawing]);

  return (
    <div className="desktop">
      <div className="window">
        <Header />
        <div className="window-content">
          <Sidebar
            drawing={drawing}
            onUpload={handleUpload}
            uploading={uploading}
            onReset={handleReset}
            messageCount={messages.length}
            activeTab={activeTab}
            onTabChange={setActiveTab}
            legend={legend}
            project={project}
            projectDrawings={projectDrawings}
            onSelectSheet={handleSelectSheet}
          />
          <main className="main-content">
            {!drawing ? (
              <UploadZone
                onUpload={handleUpload}
                uploading={uploading}
                error={error}
                legend={legend}
                onLegendUpload={handleLegendUpload}
                legendUploading={legendUploading}
                legendError={legendError}
              />
            ) : (
              <div className="content-with-tabs">
                {/* Tab bar */}
                <div className="content-tabs">
                  <button
                    className={`content-tab ${activeTab === "symbols" ? "active" : ""}`}
                    onClick={() => setActiveTab("symbols")}
                  >
                    Symbols
                    <span className="tab-badge">{drawing.total_symbols}</span>
                  </button>
                  <button
                    className={`content-tab ${activeTab === "drawing" ? "active" : ""}`}
                    onClick={() => setActiveTab("drawing")}
                  >
                    Drawing View
                  </button>
                  <button
                    className={`content-tab ${activeTab === "analysis" ? "active" : ""}`}
                    onClick={() => setActiveTab("analysis")}
                  >
                    Analysis
                    <span className="tab-badge">{drawing.analysis?.length || 0}</span>
                  </button>
                  {legend && (
                    <button
                      className={`content-tab ${activeTab === "legend" ? "active" : ""}`}
                      onClick={() => setActiveTab("legend")}
                    >
                      Legend
                      <span className="tab-badge">{legend.total_symbols}</span>
                    </button>
                  )}
                  <div className="content-tabs-fill" />
                  <span className="content-tabs-filename">
                    {project
                      ? `Sheet ${(project.drawing_ids.indexOf(drawing.drawing_id) + 1)} of ${project.drawing_ids.length}: ${drawing.filename}`
                      : drawing.filename}
                  </span>
                </div>

                {/* Tab content */}
                <div className="content-tab-body">
                  {activeTab === "symbols" ? (
                    <SymbolTable
                      symbols={drawing.symbols}
                      total={drawing.total_symbols}
                      selectedSymbol={selectedSymbol}
                      onSelectSymbol={handleSelectSymbol}
                      onOverride={handleOverride}
                      onExport={handleExport}
                      xrefWarnings={drawing.xref_warnings}
                    />
                  ) : activeTab === "drawing" ? (
                    <DrawingViewer
                      preview={preview}
                      loading={previewLoading}
                      symbols={drawing.symbols}
                      selectedSymbol={selectedSymbol}
                      onSelectSymbol={handleSelectSymbol}
                    />
                  ) : activeTab === "legend" && legend ? (
                    <LegendReview
                      legend={legend}
                      onLegendChange={handleLegendChange}
                      onReAnalyze={handleLegendReAnalyze}
                      reAnalyzing={legendUploading}
                    />
                  ) : (
                    <AnalysisLog
                      analysis={drawing.analysis || []}
                      filename={drawing.filename}
                      positionDebug={preview?.position_debug}
                    />
                  )}
                </div>
              </div>
            )}
          </main>
          <ChatPanel
            messages={messages}
            onSend={handleChat}
            disabled={!drawing}
            sending={chatSending}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
