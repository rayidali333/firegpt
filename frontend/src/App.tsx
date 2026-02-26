import React, { useState } from "react";
import { DrawingData, ChatMessage } from "./types";
import { uploadDrawing, chatWithDrawing } from "./api";
import Header from "./components/Header";
import Sidebar from "./components/Sidebar";
import UploadZone from "./components/UploadZone";
import SymbolTable from "./components/SymbolTable";
import ChatPanel from "./components/ChatPanel";
import "./App.css";

function App() {
  const [drawing, setDrawing] = useState<DrawingData | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleUpload = async (file: File) => {
    setUploading(true);
    setError(null);
    try {
      const data = await uploadDrawing(file);
      setDrawing(data);
      setMessages([]);
    } catch (e: any) {
      setError(e.message || "Upload failed");
    } finally {
      setUploading(false);
    }
  };

  const handleChat = async (message: string) => {
    if (!drawing) return;

    setMessages((prev) => [...prev, { role: "user", content: message }]);

    try {
      const response = await chatWithDrawing(drawing.drawing_id, message);
      setMessages((prev) => [
        ...prev,
        { role: "assistant", content: response },
      ]);
    } catch (e: any) {
      setMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          content: `Error: ${e.message || "Failed to get response"}`,
        },
      ]);
    }
  };

  const handleReset = () => {
    setDrawing(null);
    setMessages([]);
    setError(null);
  };

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
          />
          <main className="main-content">
            {!drawing ? (
              <UploadZone
                onUpload={handleUpload}
                uploading={uploading}
                error={error}
              />
            ) : (
              <SymbolTable
                symbols={drawing.symbols}
                total={drawing.total_symbols}
              />
            )}
          </main>
          <ChatPanel
            messages={messages}
            onSend={handleChat}
            disabled={!drawing}
          />
        </div>
      </div>
    </div>
  );
}

export default App;
