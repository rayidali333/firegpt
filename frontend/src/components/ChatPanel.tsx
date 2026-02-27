import React, { useState, useRef, useEffect } from "react";
import { MessageSquare, Upload, DollarSign, Send } from "lucide-react";
import { ChatMessage } from "../types";

interface Props {
  messages: ChatMessage[];
  onSend: (message: string) => void;
  disabled?: boolean;
  sending?: boolean;
}

const SUGGESTIONS = [
  "Give me a full device count summary",
  "How many smoke detectors are there?",
  "Estimate the total project cost",
  "What devices do I need for this bid?",
  "Generate a material takeoff list",
  "Compare device counts to typical coverage",
];

/** Simple markdown to HTML renderer for chat messages. */
function renderMarkdown(text: string): string {
  // Escape HTML
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Code blocks (```)
  html = html.replace(
    /```(\w*)\n([\s\S]*?)```/g,
    '<pre class="msg-code-block"><code>$2</code></pre>'
  );

  // Inline code
  html = html.replace(/`([^`]+)`/g, '<code class="msg-inline-code">$1</code>');

  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

  // Italic
  html = html.replace(/(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)/g, "<em>$1</em>");

  // Tables: detect lines starting with |
  const lines = html.split("\n");
  let inTable = false;
  const processed: string[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (line.startsWith("|") && line.endsWith("|")) {
      // Check if separator row
      if (/^\|[\s\-:|]+\|$/.test(line)) {
        continue; // Skip separator
      }
      const cells = line
        .split("|")
        .filter((c) => c.trim() !== "")
        .map((c) => c.trim());

      if (!inTable) {
        inTable = true;
        // First row is header
        processed.push('<table class="msg-table"><thead><tr>');
        cells.forEach((c) => processed.push(`<th>${c}</th>`));
        processed.push("</tr></thead><tbody>");
      } else {
        processed.push("<tr>");
        cells.forEach((c) => processed.push(`<td>${c}</td>`));
        processed.push("</tr>");
      }
    } else {
      if (inTable) {
        processed.push("</tbody></table>");
        inTable = false;
      }
      processed.push(line);
    }
  }
  if (inTable) {
    processed.push("</tbody></table>");
  }
  html = processed.join("\n");

  // Unordered lists
  html = html.replace(/^[-*] (.+)$/gm, "<li>$1</li>");
  html = html.replace(/((?:<li>.*<\/li>\n?)+)/g, "<ul>$1</ul>");

  // Ordered lists
  html = html.replace(/^\d+\.\s+(.+)$/gm, "<li>$1</li>");

  // Headers
  html = html.replace(/^### (.+)$/gm, '<h4 class="msg-h">$1</h4>');
  html = html.replace(/^## (.+)$/gm, '<h3 class="msg-h">$1</h3>');
  html = html.replace(/^# (.+)$/gm, '<h2 class="msg-h">$1</h2>');

  // Line breaks (but not inside tags)
  html = html.replace(/\n/g, "<br/>");

  // Clean up excessive <br/> around block elements
  html = html.replace(/<br\/>(<table|<ul|<ol|<pre|<h[234])/g, "$1");
  html = html.replace(/(<\/table>|<\/ul>|<\/ol>|<\/pre>|<\/h[234]>)<br\/>/g, "$1");

  return html;
}

export default function ChatPanel({
  messages,
  onSend,
  disabled,
  sending,
}: Props) {
  const [input, setInput] = useState("");
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const handleSubmit = () => {
    const trimmed = input.trim();
    if (!trimmed || sending || disabled) return;
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
    if (disabled || sending) return;
    onSend(text);
  };

  return (
    <div className="chat-panel">
      <div className="chat-header">
        <MessageSquare />
        <span className="chat-header-title">FireGPT Assistant</span>
      </div>

      {disabled ? (
        <div className="chat-disabled-msg">
          <Upload />
          <p>
            Upload a construction drawing to start chatting. Ask about symbol
            counts, device types, cost estimates, or get a full takeoff summary.
          </p>
        </div>
      ) : (
        <>
          <div className="chat-messages">
            {messages.length === 0 ? (
              <div className="chat-empty">
                <div className="chat-empty-icon">
                  <MessageSquare />
                </div>
                <h3>Chat with your drawing</h3>
                <p>
                  Ask about symbol counts, get cost estimates, or generate a
                  material takeoff for your bid.
                </p>
                <div className="chat-suggestions">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      className="suggestion-btn"
                      onClick={() => handleSuggestion(s)}
                    >
                      {s.toLowerCase().includes("cost") ||
                      s.toLowerCase().includes("estimate") ? (
                        <DollarSign className="suggestion-icon" />
                      ) : null}
                      <span>{s}</span>
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              <>
                {messages.map((msg, i) => (
                  <div key={i} className={`chat-message ${msg.role}`}>
                    <div className="message-meta">
                      <span className="message-role">
                        {msg.role === "user" ? "You" : "FireGPT"}
                      </span>
                    </div>
                    {msg.role === "assistant" ? (
                      <div
                        className="message-content"
                        dangerouslySetInnerHTML={{
                          __html: renderMarkdown(msg.content),
                        }}
                      />
                    ) : (
                      <div className="message-content">{msg.content}</div>
                    )}
                  </div>
                ))}
                {sending && (
                  <div className="chat-message assistant">
                    <div className="message-meta">
                      <span className="message-role">FireGPT</span>
                    </div>
                    <div className="message-content typing-indicator">
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                      <span className="typing-dot" />
                    </div>
                  </div>
                )}
              </>
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="chat-input-area">
            <div className="chat-input-wrapper">
              <textarea
                ref={inputRef}
                className="chat-input"
                placeholder="Ask about counts, costs, or bid details..."
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKeyDown}
                rows={1}
                disabled={disabled || sending}
              />
              <button
                className="chat-send-btn"
                onClick={handleSubmit}
                disabled={!input.trim() || sending || disabled}
                title="Send message"
              >
                <Send />
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
