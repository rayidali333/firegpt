# Frontend Source - SUBCLAUDE.md

## Overview

React 19 + TypeScript source code for FireGPT. Uses a retro Mac OS vintage design with three-panel layout.

## Architecture

### State Management
All state lives in App.tsx (no external state library):
- `drawing: DrawingData | null` - Currently loaded drawing data
- `messages: ChatMessage[]` - Chat conversation history
- `uploading: boolean` - Upload in progress flag
- `error: string | null` - Last upload error

### Component Tree
```
App.tsx
├── Header.tsx          (window title bar - no props)
├── Sidebar.tsx         (left nav - drawing, onUpload, uploading, onReset)
├── MainContent
│   ├── UploadZone.tsx  (when no drawing - onUpload, uploading, error)
│   └── SymbolTable.tsx (when drawing loaded - symbols, total)
└── ChatPanel.tsx       (right panel - messages, onSend, disabled)
```

### API Layer (api.ts)
- `uploadDrawing(file: File)`: POST /api/upload, FormData, returns DrawingData
- `chatWithDrawing(drawingId: string, message: string)`: POST /api/chat, JSON, returns string

### Types (types.ts)
- `SymbolInfo`: block_name, label, count, sample_locations
- `DrawingData`: drawing_id, filename, file_type, symbols[], total_symbols
- `ChatMessage`: role ("user"|"assistant"), content

## Design Details

### Retro Mac OS Theme
- Window chrome wraps entire app (desktop > window > titlebar + content)
- Traffic light buttons (red/yellow/green) in title bar
- Warm cream/beige/brown color palette throughout
- Inset shadow on input fields, gradient on buttons
- Classic raised/recessed border effects

### Three-Panel Layout
1. **Sidebar** (220px): Brand, upload button, file list, reset
2. **Content** (flexible): Upload zone or symbol table
3. **Chat** (340px): Always visible, Cursor-style AI assistant

### Chat Panel States
- **Disabled** (no drawing): Shows upload prompt message
- **Empty** (drawing loaded, no messages): Shows suggestions
- **Active** (has messages): Shows conversation with auto-scroll

## File Upload Flow
1. User clicks sidebar "Upload Drawing" OR drags file to center zone
2. File validated (.dxf/.dwg only)
3. `uploading` state set to true
4. API call to /api/upload
5. On success: drawing state set, messages cleared
6. On error: error state set, displayed in upload zone

## Current State
- All components implemented with retro Mac OS styling
- Responsive: stacks vertically on screens < 900px
- Chat always visible with disabled state when no drawing
- Upload available from both sidebar and main content area
- Lucide React icons throughout (Upload, FileText, MessageSquare, Send)
