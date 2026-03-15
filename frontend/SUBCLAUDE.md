# Frontend - SUBCLAUDE.md

## Overview

React 19 + TypeScript single-page application with a retro Mac OS vintage design aesthetic. Three-panel layout: left sidebar navigation, center content area (tabbed), right-side AI chat panel.

## Design System

### Color Palette (Warm Vintage Theme)
- Desktop background: #C2A882 (warm tan)
- Window background: #F2E8D5 (cream)
- Sidebar: #E5D5BB (warm beige)
- Content area: #F8F2E8 (light cream)
- Borders: #B8A080 (warm brown)
- Dark borders: #8B7558 (chocolate)
- Primary text: #2C1E12 (dark brown)
- Secondary text: #5C4A38 (medium brown)
- Muted text: #8C7A68 (light brown)
- Accent: #B87333 (copper/bronze)
- Traffic lights: #FF5F57 (red), #FFBD2E (yellow), #28C840 (green)

### Layout
```
+----------------------------------------------------------+
| [o][o][o]     FireGPT - Fire Alarm Analysis             | <- Title bar
+----------+----------------------------+------------------+
| SIDEBAR  |    MAIN CONTENT            |   CHAT PANEL     |
| 220px    |    flexible                |   340px          |
|          |                            |                  |
| Logo     | [Symbols] [Drawing] [Analysis] tabs           |
| Tagline  |  Upload zone (no file)     |  "AI Assistant"  |
| Upload   |  Symbol table (file loaded)|  Messages...     |
| Files    |  SVG preview (drawing tab) |  Markdown render  |
| Views    |  Analysis log              |  [Input area]    |
| Stats    |                            |                  |
+----------+----------------------------+------------------+
```

### Typography
- Main: System fonts (-apple-system, Segoe UI, Lucida Grande)
- Monospace: SF Mono, Monaco, Cascadia Code

## Components

### App.tsx
- Root component managing all state
- State: drawing, messages, uploading, error, activeTab, previewData, highlightedSymbol
- Three-panel layout: Sidebar | MainContent (tabbed) | ChatPanel
- Wrapped in retro window chrome (desktop > window > titlebar + content)
- Handles bidirectional highlighting between symbol table and drawing preview

### components/Sidebar.tsx
- Left navigation panel (220px fixed width)
- Brand section: FireGPT logo (Flame icon) + tagline "Talk to your drawing files"
- Upload button with hidden file input (.dxf, .dwg)
- Drawings section with active file indicator
- Views section: Symbols (with count badge), Drawing, Analysis (with count badge), Chat (with message count)
- Bottom stats: Types count + Devices count
- "New Drawing" reset button when file loaded
- Props: drawing, onUpload, uploading, onReset, messageCount, activeTab, onTabChange

### components/Header.tsx
- Retro window title bar (38px height)
- Traffic light buttons (red, yellow, green circles)
- Centered title: "FireGPT - Fire Alarm Symbol Analysis"
- Purely decorative (no functional props needed)

### components/UploadZone.tsx
- Centered drag-drop area in main content
- Retro styled with brown dashed border
- Two upload types: Legend (PDF/image) and Drawing (DXF/DWG)
- Auto-detect by extension on drag-drop: PDF/image → legend, DXF/DWG → drawing
- Full progress bar with staged messages for both drawing AND legend uploads
- Legend upload stages: uploading, AI vision, section scanning, symbol extraction, shape classification, verification, icon generation
- Drawing upload stages: uploading, converting, block scanning, entity detection, classification, matching, consolidation
- Legend attached indicator with filename and symbol count
- Error display for failed uploads
- Props: onUpload, uploading, error, legend, onLegendUpload, legendUploading, legendError

### components/SymbolTable.tsx
- Displays detected symbols after file upload
- Header with "Detected Symbols" title + total count badge + CSV export button
- AI-generated SVG icons per symbol (from legend parsing), fallback to shape+code markers
- Source badges: Dict (green), Legend (blue), AI (yellow), Manual (gray)
- Inline editing: click edit icon to change label/count with confirm/cancel
- MapPin icon indicates symbols with location data
- Bidirectional highlighting: click row → highlights markers on drawing
- Block variants shown for consolidated symbols
- Props: symbols, total, selectedSymbol, onSelectSymbol, onOverride, onExport, xrefWarnings

### components/ChatPanel.tsx (Cursor-style)
- Right-side panel (340px fixed width)
- Own header bar: "AI Assistant" title
- Messages area with auto-scroll
- User messages: right-aligned, copper-toned bubbles
- Assistant messages: left-aligned with full markdown rendering (tables, bold, code, lists)
- Typing indicator during AI response
- 4 suggestion buttons when empty (counts, cost estimate, device schedule, recommendations)
- Textarea input with send button
- Disabled state when no drawing loaded
- Props: messages, onSend, disabled, loading

## API Client (api.ts)
- `uploadLegend(file)`: POST /api/upload-legend with FormData → LegendData
- `uploadDrawing(file, legendId?)`: POST /api/upload with FormData + optional legend_id query param
- `chatWithDrawing(drawingId, message, history)`: POST /api/chat with JSON
- `getDrawingPreview(drawingId)`: GET /api/drawings/{id}/preview
- `getExportUrl(drawingId)`: Returns URL for GET /api/drawings/{id}/export
- `overrideSymbol(drawingId, blockName, label, count)`: PATCH symbol override

## TypeScript Types (types.ts)
- SymbolInfo: block_name, label, count, locations, color, confidence, source, block_variants, original_count, shape_code, category, legend_code, legend_shape, svg_icon
- DrawingData: drawing_id, filename, file_type, symbols, total_symbols, analysis, audit, xref_warnings, legend_texts
- ChatMessage: role ("user"|"assistant"), content, timestamp
- DrawingPreview: svg, viewBox, width, height, symbol_positions, position_debug
- LegendSymbol: code, name, category, shape, shape_code, svg_icon
- LegendData: legend_id, filename, symbols, total_symbols, systems

## Build
- Create React App (react-scripts)
- `npm start`: Dev server on :3000
- `npm run build`: Production build to /build
- Build output copied to backend/static for serving

## Current State
- All components functional with retro vintage styling
- Three-panel layout responsive (stacks on mobile)
- Tabbed content: Symbols, Drawing (SVG preview), Analysis
- Chat panel always visible with markdown rendering and typing indicator
- Bidirectional highlighting between symbol table and drawing preview
- Upload works via sidebar button or drag-drop in main area
- Legend upload with full progress bar (AI vision parsing stages)
- Drawing upload with full progress bar (parsing stages)
- Symbol table shows AI-generated SVG icons, source badges, inline editing
- Shape-coded markers on drawing view (hexagon, square, diamond, star, etc.)
- AI chat with suggestion prompts, auto-scroll, and multi-turn history
- Legend section in sidebar showing filename + symbol count
