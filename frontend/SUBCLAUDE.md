# Frontend - SUBCLAUDE.md

## Overview

React 19 + TypeScript single-page application with a retro Mac OS vintage design aesthetic. Three-panel layout: left sidebar navigation, center content area, right-side AI chat panel.

## Design System

### Color Palette (Retro Mac OS Warm Theme)
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
| [o][o][o]     DrawingIQ - Fire Alarm Analysis             | <- Title bar
+----------+----------------------------+------------------+
| SIDEBAR  |    MAIN CONTENT            |   CHAT PANEL     |
| 220px    |    flexible                |   340px          |
|          |                            |                  |
| Logo     |  Upload zone (no file)     |  "AI Assistant"  |
| Upload   |  Symbol table (file loaded)|  Messages...     |
| Files    |                            |  [Input area]    |
+----------+----------------------------+------------------+
```

### Typography
- Main: System fonts (-apple-system, Segoe UI, Lucida Grande)
- Monospace: SF Mono, Monaco, Cascadia Code

## Components

### App.tsx
- Root component managing all state
- State: drawing (DrawingData|null), messages (ChatMessage[]), uploading, error
- Three-panel layout: Sidebar | MainContent | ChatPanel
- Wrapped in retro window chrome (desktop > window > titlebar + content)

### components/Sidebar.tsx
- Left navigation panel (220px fixed width)
- Brand section: DrawingIQ logo + tagline
- Upload button with hidden file input (.dxf, .dwg)
- "Your Drawings" section with file list
- "New Drawing" reset button when file loaded
- Props: drawing, onUpload, uploading, onReset

### components/Header.tsx
- Retro window title bar (38px height)
- Traffic light buttons (red, yellow, green circles)
- Centered title: "DrawingIQ - Fire Alarm Symbol Analysis"
- Purely decorative (no functional props needed)

### components/UploadZone.tsx
- Centered drag-drop area in main content
- Retro styled with brown dashed border
- File validation: .dxf and .dwg only
- Loading spinner state during parsing
- Error display for failed uploads
- Props: onUpload, uploading, error

### components/SymbolTable.tsx
- Displays detected symbols after file upload
- Header with "Detected Symbols" title + total count badge
- List of symbols: label, block name (mono), count
- Warm brown accent colors for counts
- Empty state message if no symbols found
- Props: symbols, total

### components/ChatPanel.tsx (Cursor-style)
- Right-side panel (340px fixed width)
- Own header bar: "AI Assistant" title
- Messages area with auto-scroll
- User messages: right-aligned, copper-toned bubbles
- Assistant messages: left-aligned, bordered bubbles
- 4 suggestion buttons when empty
- Textarea input with send button
- Disabled state when no drawing loaded
- Props: messages, onSend, disabled

## API Client (api.ts)
- `uploadDrawing(file)`: POST /api/upload with FormData
- `chatWithDrawing(drawingId, message)`: POST /api/chat with JSON

## TypeScript Types (types.ts)
- SymbolInfo: block_name, label, count, sample_locations
- DrawingData: drawing_id, filename, file_type, symbols, total_symbols
- ChatMessage: role ("user"|"assistant"), content

## Build
- Create React App (react-scripts)
- `npm start`: Dev server on :3000
- `npm run build`: Production build to /build
- Build output copied to backend/static for serving

## Current State
- All components functional with retro Mac OS design
- Three-panel layout responsive (stacks on mobile)
- Chat panel always visible, disabled until drawing uploaded
- Upload works via sidebar button or drag-drop in main area
- Symbol detection results display in sortable list
- AI chat with suggestion prompts and auto-scroll
