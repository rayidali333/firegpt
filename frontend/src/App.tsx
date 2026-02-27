import React, { useState, useCallback, useEffect } from "react";
import { DrawingData, DrawingPreview, ChatMessage } from "./types";
import { uploadDrawing, getDrawingPreview, chatWithDrawing } from "./api";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import UploadZone from "./components/UploadZone";
import SymbolTable from "./components/SymbolTable";
import DrawingViewer from "./components/DrawingViewer";
import AnalysisLog from "./components/AnalysisLog";
import ChatPanel from "./components/ChatPanel";
import "./App.css";

function App() {
  const [drawing, setDrawing] = useState<DrawingData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<"symbols" | "drawing" | "analysis">("symbols");
  const [preview, setPreview] = useState<DrawingPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);
  const [chatSending, setChatSending] = useState(false);

  // Load preview when drawing changes
  useEffect(() => {
    if (!drawing) {
      setPreview(null);
      return;
    }
    setPreviewLoading(true);
    getDrawingPreview(drawing.drawing_id)
      .then(setPreview)
      .catch(() => {
        // Preview generation failed silently — drawing viewer will show empty
      })
      .finally(() => setPreviewLoading(false));
  }, [drawing]);

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

  const handleReset = () => {
    setDrawing(null);
    setMessages([]);
    setError(null);
    setActiveTab("symbols");
    setPreview(null);
    setSelectedSymbol(null);
  };

  const handleSelectSymbol = useCallback(
    (blockName: string | null) => {
      setSelectedSymbol(blockName);
    },
    []
  );

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
          />
          <main className="main-content">
            {!drawing ? (
              <UploadZone
                onUpload={handleUpload}
                uploading={uploading}
                error={error}
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
                    />
                  ) : activeTab === "drawing" ? (
                    <DrawingViewer
                      preview={preview}
                      loading={previewLoading}
                      symbols={drawing.symbols}
                      selectedSymbol={selectedSymbol}
                      onSelectSymbol={handleSelectSymbol}
                    />
                  ) : (
                    <AnalysisLog
                      analysis={drawing.analysis || []}
                      filename={drawing.filename}
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
