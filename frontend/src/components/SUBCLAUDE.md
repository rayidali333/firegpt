# Components - SUBCLAUDE.md

## Overview

React components for FireGPT, styled with a warm vintage aesthetic.

## Component Details

### Header.tsx
- **Purpose**: Retro window title bar with traffic light buttons
- **Props**: None (purely decorative)
- **Renders**: Three colored circles (red/yellow/green) + centered title text "FireGPT - Fire Alarm Symbol Analysis"
- **CSS classes**: .titlebar, .titlebar-buttons, .titlebar-btn, .titlebar-title

### Sidebar.tsx
- **Purpose**: Left navigation panel with branding, upload, file management, view switching
- **Props**: drawing (DrawingData|null), onUpload (file => void), uploading (bool), onReset (() => void), messageCount (number), activeTab (string), onTabChange (tab => void)
- **Features**:
  - Brand section: FireGPT logo (Flame icon) + tagline "Talk to your drawing files"
  - Upload button with hidden file input (validates .dxf/.dwg)
  - Drawings section with active file indicator
  - Views section with tab navigation: Symbols, Drawing, Analysis, Chat (each with count badges)
  - Bottom stats: Types count + Devices count
  - "New Drawing" reset button (shown when file loaded)
- **CSS classes**: .sidebar, .sidebar-brand, .sidebar-logo, .sidebar-tagline, .sidebar-section, .sidebar-nav-item, .sidebar-badge, .sidebar-stats, .sidebar-action-btn

### UploadZone.tsx
- **Purpose**: Centered drag-drop file upload area
- **Props**: onUpload (file => void), uploading (bool), error (string|null)
- **Features**:
  - Drag and drop support with visual feedback
  - Click to browse with hidden file input
  - File validation (.dxf/.dwg only)
  - Loading spinner during parse
  - Error display
- **CSS classes**: .upload-container, .upload-zone, .upload-icon, .upload-title, .format-badge, .spinner

### SymbolTable.tsx
- **Purpose**: Display detected fire alarm symbols after file parsing
- **Props**: symbols (SymbolInfo[]), total (number), onSymbolClick (callback), highlightedSymbol (string|null)
- **Features**:
  - Header with title + total count badge
  - Color-coded dots per symbol category
  - Confidence badges (high/medium) and source indicators (dictionary/AI)
  - Bidirectional highlighting: click row → highlights markers on drawing preview
  - Block variants display for consolidated symbols
  - Hover highlight on rows
  - Empty state message
- **CSS classes**: .symbol-table, .symbol-table-header, .symbol-row, .symbol-label, .symbol-count, .symbol-color-dot, .confidence-badge

### ChatPanel.tsx (Cursor-style)
- **Purpose**: Right-side AI chat panel
- **Props**: messages (ChatMessage[]), onSend (msg => void), disabled (bool), loading (bool)
- **Features**:
  - Own header bar with "AI Assistant" title
  - Disabled state: shows upload prompt when no drawing
  - Empty state: shows 4 suggestion buttons (counts, cost estimate, device schedule, recommendations)
  - Active state: message bubbles with auto-scroll
  - User messages: right-aligned, copper/bronze bubbles
  - AI messages: left-aligned with full markdown rendering (tables, bold, code blocks, lists)
  - Typing indicator during AI response
  - Textarea input + send button
  - Enter to send, Shift+Enter for newline
- **CSS classes**: .chat-panel, .chat-header, .chat-messages, .chat-message, .chat-input-area, .chat-send-btn, .chat-suggestion-btn, .typing-indicator

## Current State
- All 5 components implemented and functional
- Consistent warm vintage styling across all components
- Responsive behavior defined in App.css media queries
- Icons from lucide-react: Upload, FileText, MessageSquare, Send, Flame, BarChart3, Eye, ClipboardList
- Bidirectional highlighting between SymbolTable and Drawing preview
- Chat panel with full markdown rendering and typing indicator
