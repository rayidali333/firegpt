# Components - SUBCLAUDE.md

## Overview

React components for FireGPT, styled with retro Mac OS vintage aesthetic.

## Component Details

### Header.tsx
- **Purpose**: Retro window title bar with traffic light buttons
- **Props**: None (purely decorative)
- **Renders**: Three colored circles (red/yellow/green) + centered title text
- **CSS classes**: .titlebar, .titlebar-buttons, .titlebar-btn, .titlebar-title

### Sidebar.tsx
- **Purpose**: Left navigation panel with branding, upload, file management
- **Props**: drawing (DrawingData|null), onUpload (file => void), uploading (bool), onReset (() => void)
- **Features**:
  - Brand section with FireGPT logo + tagline
  - Upload button with hidden file input (validates .dxf/.dwg)
  - "Your Drawings" section with active file indicator
  - "New Drawing" reset button (shown when file loaded)
- **CSS classes**: .sidebar, .sidebar-brand, .sidebar-logo, .sidebar-upload-btn, .sidebar-file, .sidebar-reset-btn

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
- **Props**: symbols (SymbolInfo[]), total (number)
- **Features**:
  - Header with title + total count badge
  - List of symbols: human label, block name (monospace), count (accent color)
  - Hover highlight on rows
  - Empty state message
- **CSS classes**: .symbol-table, .symbol-table-header, .symbol-row, .symbol-label, .symbol-count

### ChatPanel.tsx
- **Purpose**: Right-side AI chat panel (Cursor-style)
- **Props**: messages (ChatMessage[]), onSend (msg => void), disabled (bool)
- **Features**:
  - Own header bar with "AI Assistant" title
  - Disabled state: shows upload prompt when no drawing
  - Empty state: shows 4 suggestion buttons
  - Active state: message bubbles with auto-scroll
  - User messages: right-aligned, copper/bronze bubbles
  - AI messages: left-aligned, bordered white bubbles
  - Textarea input + send button
  - Enter to send, Shift+Enter for newline
- **CSS classes**: .chat-panel, .chat-header, .chat-messages, .chat-message, .chat-input-area, .chat-send-btn

## Current State
- All 5 components implemented and functional
- Consistent retro Mac OS styling across all components
- Responsive behavior defined in App.css media queries
- Icons from lucide-react: Upload, FileText, MessageSquare, Send
