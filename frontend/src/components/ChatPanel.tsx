import React, { useState, useRef, useEffect } from "react";
import { MessageSquare, Send } from "lucide-react";
import { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  onSend: (message: string) => void;
}

const SUGGESTIONS = [
  "How many smoke detectors are there?",
  "Give me a full device count summary",
  "List all symbol types found",
  "What devices do I need for this bid?",
];

export default function ChatPanel({ messages, onSend }: Props) {
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    // Detect when a response comes back
    if (messages.length > 0 && messages[messages.length - 1].role === "assistant") {
      setSending(false);
    }
  }, [messages]);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || sending) return;
    setSending(true);
    onSend(trimmed);
    setInput("");
    inputRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSuggestion = (text: string) => {
    setSending(true);
    onSend(text);
  };

  return (
    <div className="chat-panel">
      <div className="chat-messages">
        {messages.length === 0 ? (
          <div className="chat-empty">
            <MessageSquare />
            <h3>Chat with your drawing</h3>
            <p>
              Ask questions about symbol counts, device types, or get a full
              takeoff summary for your bid.
            </p>
            <div className="chat-suggestions">
              {SUGGESTIONS.map((s) => (
                <button
                  key={s}
                  className="suggestion-btn"
                  onClick={() => handleSuggestion(s)}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((msg, i) => (
            <div key={i} className={`chat-message ${msg.role}`}>
              <div className="message-content">{msg.content}</div>
            </div>
          ))
        )}
        <div ref={messagesEndRef} />
      </div>
      <div className="chat-input-area">
        <div className="chat-input-wrapper">
          <textarea
            ref={inputRef}
            className="chat-input"
            placeholder="Ask about your drawing..."
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            rows={1}
          />
          <button
            className="chat-send-btn"
            onClick={handleSubmit}
            disabled={!input.trim() || sending}
          >
            <Send />
          </button>
        </div>
      </div>
    </div>
  );
}
