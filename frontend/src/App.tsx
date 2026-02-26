import React, { useState } from "react";
import { DrawingData, ChatMessage } from "./types";
import { uploadDrawing, chatWithDrawing } from "./api";
import UploadZone from "./components/UploadZone";
import SymbolTable from "./components/SymbolTable";
import ChatPanel from "./components/ChatPanel";
import Header from "./components/Header";
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
    <div className="app">
      <Header drawing={drawing} onReset={handleReset} />
      <main className="main-content">
        {!drawing ? (
          <UploadZone
            onUpload={handleUpload}
            uploading={uploading}
            error={error}
          />
        ) : (
          <div className="workspace">
            <div className="left-panel">
              <SymbolTable symbols={drawing.symbols} total={drawing.total_symbols} />
            </div>
            <div className="right-panel">
              <ChatPanel messages={messages} onSend={handleChat} />
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

export default App;
