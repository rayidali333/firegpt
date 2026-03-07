# Frontend Source - SUBCLAUDE.md

## Overview

React 19 + TypeScript source code for FireGPT. Uses a warm vintage design with three-panel layout and tabbed content area.

## Architecture

### State Management
All state lives in App.tsx (no external state library):
- `drawing: DrawingData | null` - Currently loaded drawing data
- `messages: ChatMessage[]` - Chat conversation history
- `uploading: boolean` - Upload in progress flag
- `error: string | null` - Last upload error
- `activeTab: "symbols" | "drawing" | "analysis"` - Current content tab
- `previewData: PreviewData | null` - Cached SVG preview
- `highlightedSymbol: string | null` - Currently highlighted symbol for bidirectional linking
- `loading: boolean` - Chat response loading state

### Component Tree
```
App.tsx
├── Header.tsx          (window title bar - no props)
├── Sidebar.tsx         (left nav - drawing, upload, tabs, stats)
├── MainContent (tabbed)
│   ├── UploadZone.tsx  (when no drawing - onUpload, uploading, error)
│   ├── SymbolTable.tsx (symbols tab - symbols, highlighting, overrides)
│   ├── DrawingView     (drawing tab - SVG preview with symbol overlay)
│   └── AnalysisLog     (analysis tab - step-by-step analysis entries)
└── ChatPanel.tsx       (right panel - messages, markdown, suggestions)
```

### API Layer (api.ts)
- `uploadDrawing(file: File)`: POST /api/upload, FormData, returns DrawingData
- `chatWithDrawing(drawingId: string, message: string, history: ChatMessage[])`: POST /api/chat, JSON, returns string
- `getDrawingPreview(drawingId: string)`: GET /api/drawings/{id}/preview, returns PreviewData
- `exportDrawingCSV(drawingId: string)`: GET /api/drawings/{id}/export, triggers download
- `overrideSymbol(drawingId, blockName, label, count)`: PATCH, returns updated symbol

### Types (types.ts)
- `SymbolInfo`: block_name, label, count, locations, color, confidence, source, block_variants, original_count
- `DrawingData`: drawing_id, filename, file_type, symbols[], total_symbols, analysis[], audit[], xref_warnings[], legend_texts[]
- `ChatMessage`: role ("user"|"assistant"), content
- `PreviewData`: svg, viewBox, width, height, symbol_positions, position_debug

## Design Details

### Warm Vintage Theme
- Window chrome wraps entire app (desktop > window > titlebar + content)
- Traffic light buttons (red/yellow/green) in title bar
- Warm cream/beige/brown color palette throughout
- Inset shadow on input fields, gradient on buttons
- Classic raised/recessed border effects

### Three-Panel Layout
1. **Sidebar** (220px): Brand + tagline, upload button, file list, view tabs, stats
2. **Content** (flexible): Tabbed — Symbols table, Drawing preview, Analysis log
3. **Chat** (340px): Always visible, Cursor-style AI assistant with markdown

### Content Tabs
- **Symbols**: Device table with counts, colors, confidence, bidirectional highlighting
- **Drawing**: Interactive SVG preview with zoom/pan and color-coded symbol markers
- **Analysis**: Step-by-step log of parsing and classification decisions

### Chat Panel States
- **Disabled** (no drawing): Shows upload prompt message
- **Empty** (drawing loaded, no messages): Shows 4 suggestion buttons
- **Active** (has messages): Shows conversation with markdown rendering and auto-scroll
- **Loading**: Shows typing indicator while waiting for Claude response

## File Upload Flow
1. User clicks sidebar "Upload Drawing" OR drags file to center zone
2. File validated (.dxf/.dwg only)
3. `uploading` state set to true
4. API call to /api/upload
5. On success: drawing state set, messages cleared, preview fetched
6. On error: error state set, displayed in upload zone

## Current State
- All components implemented with warm vintage styling
- Responsive: stacks vertically on screens < 900px
- Tabbed content with Symbols, Drawing, Analysis views
- Bidirectional highlighting between symbol table and drawing preview
- Chat always visible with markdown rendering, typing indicator, multi-turn history
- Upload available from both sidebar and main content area
- Lucide React icons throughout (Upload, FileText, MessageSquare, Send, Flame, BarChart3, Eye, ClipboardList)
