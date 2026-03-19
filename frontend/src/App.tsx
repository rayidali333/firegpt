import React, { useState, useCallback, useEffect } from "react";
import { DrawingData, DrawingPreview, ChatMessage, LegendData } from "./types";
import { uploadDrawing, uploadLegend, matchLegend, generateIcons, getDrawingPreview, chatWithDrawing, overrideSymbol, getExportUrl } from "./api";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import UploadZone from "./components/UploadZone";
import SymbolTable from "./components/SymbolTable";
import DrawingViewer from "./components/DrawingViewer";
import AnalysisLog from "./components/AnalysisLog";
import ChatPanel from "./components/ChatPanel";
import LegendTable from "./components/LegendTable";
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
  const [legendSkipped, setLegendSkipped] = useState(false);
  const [matching, setMatching] = useState(false);
  const [matchDone, setMatchDone] = useState(false);
  const [generatingIcons, setGeneratingIcons] = useState(false);
  const [iconsDone, setIconsDone] = useState(false);

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

  // Auto-match symbols to legend when both are available
  useEffect(() => {
    if (!drawing || !legend || matchDone || matching) return;

    setMatching(true);
    console.log("[FireGPT] Auto-matching symbols to legend...");

    matchLegend(drawing.drawing_id, legend.legend_id)
      .then((result) => {
        console.log(
          `[FireGPT] Matching complete: ${result.matched}/${result.total_symbols} matched`
        );
        // Update drawing symbols with match data
        setDrawing((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            symbols: result.symbols,
          };
        });
        setMatchDone(true);
      })
      .catch((e) => {
        console.warn("[FireGPT] Legend matching failed:", e);
        setMatchDone(true); // Don't retry on failure
      })
      .finally(() => setMatching(false));
  }, [drawing, legend, matchDone, matching]);

  // Auto-generate icons after matching completes
  useEffect(() => {
    if (!drawing || !matchDone || iconsDone || generatingIcons) return;
    // Only generate if at least one symbol has a matched legend
    const hasMatches = drawing.symbols.some((s) => s.source === "legend");
    if (!hasMatches) {
      setIconsDone(true);
      return;
    }

    setGeneratingIcons(true);
    console.log("[FireGPT] Generating SVG icons for matched symbols...");

    generateIcons(drawing.drawing_id)
      .then((result) => {
        console.log(
          `[FireGPT] Icon generation complete: ${result.generated} generated, ${result.failed} failed`
        );
        setDrawing((prev) => {
          if (!prev) return prev;
          return { ...prev, symbols: result.symbols };
        });
        setIconsDone(true);
      })
      .catch((e) => {
        console.warn("[FireGPT] Icon generation failed:", e);
        setIconsDone(true);
      })
      .finally(() => setGeneratingIcons(false));
  }, [drawing, matchDone, iconsDone, generatingIcons]);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const data = await uploadDrawing(file);
      setDrawing(data);
      setMessages([]);
      setActiveTab("symbols");
      setSelectedSymbol(null);
      setPreview(null);
      setMatchDone(false);
      setIconsDone(false);
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
    setMessages((prev) => [...prev, userMsg]);
    setChatSending(true);

    try {
      // Send full conversation history for multi-turn context
      const response = await chatWithDrawing(
        drawing.drawing_id,
        message,
        messages
      );
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response, timestamp: Date.now() },
      ]);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${e.message || "Failed to get response"}`,
          timestamp: Date.now(),
        },
      ]);
    } finally {
      setChatSending(false);
    }
  };

  const handleLegendUpload = async (file: File) => {
    setLegendUploading(true);
    setError(null);
    try {
      const data = await uploadLegend(file);
      setLegend(data);
      setMatchDone(false); // Trigger re-matching with new legend
      setIconsDone(false);
    } catch (e: any) {
      setError(e.message || "Legend upload failed");
    } finally {
      setLegendUploading(false);
    }
  };

  const handleLegendSkip = () => {
    setLegendSkipped(true);
  };

  const handleReset = () => {
    setDrawing(null);
    setMessages([]);
    setError(null);
    setActiveTab("symbols");
    setPreview(null);
    setSelectedSymbol(null);
    setLegend(null);
    setLegendSkipped(false);
    setMatchDone(false);
    setMatching(false);
    setIconsDone(false);
    setGeneratingIcons(false);
  };

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
            legend={legend}
            onUpload={handleUpload}
            uploading={uploading}
            onReset={handleReset}
            messageCount={messages.length}
            activeTab={activeTab}
            onTabChange={setActiveTab}
          />
          <main className="main-content">
            {!drawing ? (
              <UploadZone
                onUpload={handleUpload}
                uploading={uploading}
                error={error}
                legend={legend}
                legendUploading={legendUploading}
                legendSkipped={legendSkipped}
                onLegendUpload={handleLegendUpload}
                onLegendSkip={handleLegendSkip}
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
                      <span className="tab-badge">{legend.total_device_types}</span>
                    </button>
                  )}
                  <div className="content-tabs-fill" />
                  <span className="content-tabs-filename">
                    {drawing.filename}
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
                    <LegendTable
                      legend={legend}
                      icons={drawing.symbols.reduce((acc, s) => {
                        if (s.svg_icon && s.matched_legend) {
                          acc[s.matched_legend.name] = s.svg_icon;
                        }
                        return acc;
                      }, {} as Record<string, string>)}
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
