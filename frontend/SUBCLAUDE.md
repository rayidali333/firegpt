# Frontend - SUBCLAUDE.md

## Overview

React 19 + TypeScript single-page application with a Mac OS 9 Platinum design aesthetic. Three-panel layout: left sidebar navigation, center content area (tabbed), right-side AI chat panel. Features a two-step upload flow (optional legend → drawing) with full pipeline loading.

## Design System

### Color Palette (Mac OS 9 Platinum)
- Desktop background: #3B9B4A (green)
- Window background: #DDDDDD (light gray)
- Panel background: #EEEEEE (lighter gray)
- Content area: #FFFFFF (white)
- Sidebar: #DDDDDD (same as window)
- Bevel light: #FFFFFF, Bevel mid: #CCCCCC, Bevel dark: #888888
- Primary text: #000000 (black)
- Secondary text: #333333
- Muted text: #666666
- Accent: #336699 (blue)
- Highlight: #336699 bg + #FFFFFF text
- Danger: #CC3333, Success: #27AE60
- Traffic lights: #FF5F57 (red), #FFBD2E (yellow), #28C840 (green)

### Layout
```
+----------------------------------------------------------+
| [o][o][o]            FireGPT                              | <- Title bar (28px)
+----------+----------------------------+------------------+
| SIDEBAR  |    MAIN CONTENT            |   CHAT PANEL     |
| 200px    |    flexible                |   340px          |
|          |                            |                  |
| Logo     | [Symbols] [Drawing] [Analysis] [Legend] tabs   |
| Tagline  |  Upload zone (no file)     |  "FireGPT Asst"  |
| Upload   |  Symbol table (file loaded)|  Messages...     |
| Files    |  SVG preview + icons       |  Markdown render  |
| Views    |  Analysis log              |  [Input area]    |
| Stats    |  Legend table              |                  |
+----------+----------------------------+------------------+
```

### Typography
- Main: Lucida Grande, Geneva, -apple-system, Segoe UI, Helvetica, Arial
- Monospace: Monaco, Courier New
- Base size: 12px, Small: 11px, Large: 13px

### Border Style
- Classic 3D beveled: light top-left (#FFFFFF), dark bottom-right (#888888)
- No border-radius (square edges throughout)

## Components

### App.tsx
- Root component managing all state
- State: drawing, messages, uploading, uploadStage, error, activeTab, preview, previewLoading, selectedSymbol, chatSending, legend, legendUploading, legendSkipped, matching, matchDone, generatingIcons, iconsDone
- **Upload pipeline**: `handleUpload` runs upload → matchLegend → generateIcons sequentially while `uploading=true`, only reveals results when all steps complete
- Preview useEffect depends on `drawingId` (string), not `drawing` (object), to prevent redundant re-fetches
- CSV export via temporary `<a download>` element (avoids popup blocking)
- Three-panel layout: Sidebar | MainContent (tabbed) | ChatPanel
- Bidirectional highlighting between symbol table and drawing preview

### components/Sidebar.tsx
- Left navigation panel (200px fixed width)
- Brand section: FireGPT logo (Flame icon) + tagline
- Upload Drawing button with hidden file input
- Drawings section with active file indicator
- Views section: Symbols, Drawing, Analysis, Chat, Legend (with count badges)
- Bottom stats: Types count + Devices count
- "New Drawing" reset button when file loaded

### components/Header.tsx
- Mac OS 9 window title bar (28px height)
- Traffic light buttons (red, yellow, green circles)
- Centered title: "FireGPT"

### components/UploadZone.tsx
- Two-step upload flow:
  - Step 1: Legend upload (optional) — PDF, PNG, JPG with skip button
  - Step 2: Drawing upload — DXF, DWG with drag-drop
- `upload-inner` flex-column wrapper for proper vertical centering
- Loading state shows simulated progress bar with real stage labels from `uploadStage` prop
- Progress covers full pipeline: upload → matching → icon generation
- Legend success banner when legend is loaded
- Step indicator dots (completed/active/pending)
- Props: onUpload, uploading, uploadStage, error, legend, legendUploading, legendSkipped, onLegendUpload, onLegendSkip

### components/SymbolTable.tsx
- Displays detected symbols after file upload
- Header with "Detected Symbols" title + total count badge + CSV export button
- Inline SVG icons next to symbol labels (when available from icon generation)
- Color-coded dots as fallback for symbols without icons
- Source badges: "Legend" (green), "Dict" (blue), "AI" (amber), "Manual" (gray)
- Manual override: inline editing of label and count
- Bidirectional highlighting: click row → highlights markers on drawing
- Block variant names shown for consolidated symbols

### components/DrawingViewer.tsx
- Interactive SVG floor plan with zoom/pan (scroll wheel + drag)
- SVG icon rendering pipeline:
  - `parseSvgIcon()`: extracts viewBox + inner content from SVG strings
  - `iconDefs` memo: builds `<symbol>` definitions keyed by block_name
  - Icons defined once in `<defs>`, reused via `<use href>` at every position
- **Default mode**: White background disc + SVG icon (3x marker radius), falls back to colored circles
- **Selected mode**: SVG icon with numbered badge overlay (top-right corner), falls back to numbered circles
- Legend bar: inline SVG icons replace colored dots when available
- Toolbar: zoom in/out, reset view, symbol toggle
- Selection info bar with position count and clear button
- Loading state with simulated progress bar and stage labels

### components/ChatPanel.tsx
- Right-side panel (340px fixed width)
- Header: "FireGPT Assistant"
- Messages with auto-scroll and markdown rendering (tables, bold, code, lists)
- User messages right-aligned, assistant messages left-aligned
- Typing indicator during AI response
- 6 suggestion buttons when empty
- Textarea input with send button
- Disabled state when no drawing loaded

### components/LegendTable.tsx
- Displays extracted legend devices after legend upload
- SVG icon preview next to each device (when generated)
- Device name, abbreviation, category, symbol description
- Color-coded category badges

### components/AnalysisLog.tsx
- Chronological list of analysis steps from parsing, matching, and icon generation
- Color-coded by type: info (blue), success (green), warning (amber), error (red)
- Position debug information from preview generation

## API Client (api.ts)
- `uploadDrawing(file)`: POST /api/upload
- `getDrawingPreview(drawingId)`: GET /api/drawings/{id}/preview
- `chatWithDrawing(drawingId, message, history)`: POST /api/chat
- `overrideSymbol(drawingId, blockName, label, count)`: PATCH symbol override
- `getExportUrl(drawingId)`: Returns CSV export URL string
- `uploadLegend(file)`: POST /api/legend/upload
- `matchLegend(drawingId, legendId)`: POST /api/drawings/{id}/match-legend
- `generateIcons(drawingId)`: POST /api/drawings/{id}/generate-icons

## TypeScript Types (types.ts)
- **SymbolInfo**: block_name, label, count, locations, color, confidence, source, block_variants, original_count, matched_legend (LegendDevice), match_confidence, original_label, svg_icon
- **LegendDevice**: name, abbreviation, category, symbol_description, svg_icon, color
- **DrawingData**: drawing_id, filename, file_type, symbols, total_symbols, analysis, audit, xref_warnings, legend_texts
- **LegendData**: legend_id, filename, devices, categories_found, total_device_types, analysis, notes
- **DrawingPreview**: svg, viewBox, width, height, symbol_positions, position_debug
- **ChatMessage**: role, content, timestamp

## Build
- Create React App (react-scripts)
- `npm start`: Dev server on :3000
- `npm run build`: Production build to /build
- Build output copied to backend/static for serving

## Current State
- All components functional with Mac OS 9 Platinum styling
- Three-panel layout responsive (stacks on mobile)
- Tabbed content: Symbols, Drawing (SVG preview + icons), Analysis, Legend
- Two-step upload with full pipeline loading (legend → drawing → match → icons)
- SVG icons rendered in symbol table, legend table, and drawing view
- Chat panel always visible with markdown rendering and typing indicator
- Bidirectional highlighting between symbol table and drawing preview
- CSV export via anchor download element
- Upload zone properly centered with flex-column inner wrapper
