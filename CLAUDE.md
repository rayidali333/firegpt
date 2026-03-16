# FireGPT

## Project Overview

FireGPT is a full-stack web application built for fire alarm contractors. Users upload construction drawings (DXF/DWG format), the app automatically detects and counts all fire alarm symbols (smoke detectors, heat detectors, pull stations, horn/strobes, etc.), renders an interactive SVG preview with color-coded device markers, and provides an AI chat interface powered by Claude to ask questions about the extracted data.

**Tagline**: "Talk to your drawing files"

**Client brief**: Build a tool that lets fire alarm contractors upload CAD drawings, auto-detect all device symbols, get accurate counts, visualize them on the floor plan, and chat with the data for bidding and takeoff purposes.

## Architecture

### Tech Stack
- **Backend**: Python 3.11 + FastAPI + ezdxf (DXF parsing) + ODA File Converter (DWG→DXF)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Sonnet 4 via Anthropic API (async client) — used for both chat AND block classification
- **Deployment**: Multi-stage Docker build on Render
- **No database**: In-memory dictionary storage (drawings_store)

### Project Structure
```
/
├── CLAUDE.md                # This file - main project documentation
├── Dockerfile               # Multi-stage Docker (Node build + Python serve)
├── docker-compose.yml       # Local development orchestration
├── build.sh                 # Render deployment build script
├── render.yaml              # Render platform configuration
├── backend/                 # Python FastAPI backend
│   ├── SUBCLAUDE.md         # Backend-specific documentation
│   ├── app/
│   │   ├── main.py          # FastAPI routes, CORS, static serving, symbol consolidation
│   │   ├── models.py        # Pydantic models (SymbolInfo, ParseResponse, PreviewResponse, etc.)
│   │   ├── parser.py        # DXF/DWG parsing engine (57 known symbols + AI classification)
│   │   ├── preview.py       # SVG preview generation with symbol overlay markers
│   │   └── chat.py          # Claude AI integration (chat + block classification)
│   ├── requirements.txt     # Python dependencies
│   └── uploads/             # Uploaded drawing files
└── frontend/                # React TypeScript frontend
    ├── SUBCLAUDE.md          # Frontend-specific documentation
    ├── src/
    │   ├── App.tsx           # Main app - 3-panel layout (sidebar | content | chat)
    │   ├── App.css           # Complete retro Mac OS themed stylesheet
    │   ├── index.css         # Global base styles
    │   ├── api.ts            # API client (uploadDrawing, chatWithDrawing, getPreview, etc.)
    │   ├── types.ts          # TypeScript interfaces
    │   └── components/
    │       ├── Sidebar.tsx   # Left nav - logo, upload button, file list, view switching
    │       ├── Header.tsx    # Retro window title bar with traffic lights
    │       ├── UploadZone.tsx # Drag-drop file upload (center panel)
    │       ├── SymbolTable.tsx # Symbol detection results table with bidirectional highlighting
    │       └── ChatPanel.tsx  # Right-side AI chat (Cursor-style) with markdown rendering
    └── package.json
```

## Current State (Latest)

### What's working
- DXF/DWG file upload and parsing via ezdxf
- DWG→DXF conversion via ODA File Converter
- Symbol detection: 57 known patterns (dictionary) + AI classification for ambiguous blocks
- AI chat via Claude Sonnet 4 with full symbol context injection + multi-turn history
- Interactive SVG drawing preview with zoom/pan
- Color-coded symbol overlay markers on floor plan with bidirectional highlighting
- OCS→WCS coordinate recovery for INSERT entities with mirrored coordinates (Revit exports)
- Schedule detection: automatically removes device legend/schedule entries from floor plan markers
- XREF prefix handling: AutoCAD `$0$`, ODA `|`, BricsCAD backtick separators
- MINSERT entity support for arrayed block insertions
- Symbol consolidation: merges block variants of same device type into single rows
- Manual count overrides with audit trail
- CSV export of symbol data
- Cost estimation via AI with 2024-2025 US market pricing
- Retro Mac OS vintage UI design with warm cream/beige palette
- Three-panel layout: sidebar navigation | main content (tabs) | AI chat
- Tabbed content: Symbols table, Drawing view, Analysis log
- Docker deployment on Render
- Static file serving (React build served by FastAPI)

### Design System
The UI uses a warm, vintage aesthetic:
- **Color palette**: Warm tan desktop, cream windows, beige sidebar, brown accents
- **Window chrome**: Classic title bar with traffic light buttons (red/yellow/green)
- **Typography**: System fonts (Lucida Grande, Geneva), Monaco monospace
- **Layout**: Three-panel (sidebar 220px | flexible content | chat 340px)
- **Responsive**: Stacks vertically on mobile (<900px)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/upload` | Upload DXF/DWG → parse symbols (dictionary + AI) → return ParseResponse |
| `GET` | `/api/drawings/{id}` | Retrieve cached drawing data by UUID |
| `GET` | `/api/drawings/{id}/preview` | Generate/return cached SVG preview with symbol positions |
| `PATCH` | `/api/drawings/{id}/symbols/{block}` | Manual count/label override for a symbol |
| `GET` | `/api/drawings/{id}/export` | Export symbol data as CSV |
| `GET` | `/api/drawings` | List all uploaded drawings |
| `POST` | `/api/chat` | Send message + drawing_id + history → Claude response |
| `GET` | `/{path}` | SPA catch-all (serves React index.html) |

## Data Flow

```
1. User uploads DXF/DWG file (drag-drop or browse)
2. Backend saves file, converts DWG→DXF if needed (ODA File Converter)
3. Parser scans INSERT/MINSERT entities, groups by block name
4. Fast-path: auto-labels using 57 known fire alarm symbol patterns
5. AI-path: sends ambiguous blocks to Claude with full drawing context for classification
6. Consolidates block variants of same device type into single rows
7. Returns ParseResponse with symbols, counts, analysis log, audit trail
8. Frontend displays symbol table in center panel
9. Drawing preview: renders DXF geometry as SVG, overlays color-coded markers
10. Symbol positions recovered via OCS→WCS transforms, schedule filtering, X-negation
11. User asks questions in right-side chat panel
12. Backend injects full symbol JSON into Claude system prompt
13. Claude responds with accurate counts, cost estimates, and analysis
14. Chat continues with full drawing context and conversation history
```

## Key Design Decisions

1. **No database** - In-memory dict storage. Drawings are transient per session. Keeps deployment simple.
2. **AI-first classification** - Dictionary matching for known patterns, Claude AI for everything else. Handles any naming convention.
3. **Direct prompt injection** - All symbol data (<5KB JSON) goes into Claude's system prompt. No RAG needed at this scale.
4. **DXF as source of truth** - Counts INSERT entities (block insertions), not pixel analysis. Industry-standard accuracy.
5. **OCS→WCS recovery** - Handles Revit/AutoCAD exports where INSERT coordinates are stored in OCS with mirrored X axis.
6. **Multi-stage Docker** - Single container: Node builds React, Python serves API + static files.
7. **Retro UI** - Warm, distinctive aesthetic that stands out from typical dark-mode dev tools. Inviting for contractors.
8. **Always-visible chat** - Chat panel is always shown (Cursor-style), disabled state when no drawing loaded.
9. **Symbol consolidation** - Different block names mapping to same device type merged into single rows for contractor clarity.

## Development

```bash
# Local development
docker-compose up

# Manual build
cd frontend && npm run build
cd backend && uvicorn app.main:app --reload

# Production build
bash build.sh

# Deploy
git push origin main  # Render auto-deploys from main
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for chat and AI classification |
| `UPLOAD_DIR` | No | Upload directory (default: ./uploads) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `PORT` | No | Server port (default: 8000, Render sets automatically) |

## Change Log

### v1.1.0 - Symbol Position Recovery & OCS Fix
- **OCS→WCS Recovery**: Fixed missing markers for smoke detectors, speakers, and heat detectors in Revit-exported drawings
- **X-Negation Fallback**: Handles INSERT entities with OCS extrusion vector (0,0,-1) causing mirrored X coordinates
- **Schedule Detection**: Automatically identifies and removes device schedule/legend entries (vertical lists at X≈0)
- **Fuzzy XREF Matching**: Enhanced block name matching across AutoCAD `$0$`, ODA `|`, BricsCAD backtick formats
- **MINSERT Support**: Handles arrayed block insertions across all scan passes
- **Tagline Update**: Changed from "Fire Alarm Intelligence" to "Talk to your drawing files"
- **New Favicon**: Custom flame-themed SVG/ICO favicon

### v1.0.0 - Professional Platform Release
- **Drawing Visualization**: Interactive SVG preview with zoom/pan, renders DXF geometry (lines, polylines, circles, arcs, ellipses, splines)
- **Symbol Overlay**: Color-coded markers on drawing preview showing exact symbol placement locations
- **Bidirectional Highlighting**: Click symbols in table → highlights on drawing, click markers on drawing → highlights in table
- **AI Block Classification**: Claude classifies ambiguous blocks using full drawing context (layers, legend text, attributes)
- **Symbol Consolidation**: Merges block variants of same device type into single rows
- **Chat History**: Full multi-turn conversation support — Claude remembers the entire conversation context
- **Cost Estimation**: AI-powered project cost estimates with detailed material + labor breakdowns using real market pricing
- **Enhanced Chat**: Markdown rendering (tables, bold, code, lists), typing indicator, improved suggestions
- **Tabbed Content View**: Switch between "Symbols" table, "Drawing View", and "Analysis" with tab navigation
- **Symbol Colors**: Category-based color coding for all 57 symbol types (detectors=red, notification=blue, control=purple, etc.)
- **Manual Overrides**: Edit symbol counts/labels with audit trail tracking original values
- **CSV Export**: Download symbol data as CSV for device schedule comparison
- **Backend Preview API**: `/api/drawings/{id}/preview` endpoint generates and caches SVG previews
- **Enhanced System Prompt**: Detailed fire alarm cost estimation guidelines with 2024-2025 US market rates
- **Sidebar Improvements**: View switching, device/type stats, Flame icon branding
- **Max tokens**: Increased Claude response limit from 1024 to 4096 tokens

### v0.2.0 - Retro UI Redesign
- Complete UI overhaul to retro Mac OS vintage aesthetic
- Added three-panel layout: sidebar | content | AI chat
- Added Sidebar component with logo, upload button, file list
- Redesigned Header as classic window title bar with traffic lights
- Added Cursor-style always-visible chat panel on right side
- Warm cream/beige/brown color palette throughout
- Classic inset/raised border effects
- Added CLAUDE.md and SUBCLAUDE.md documentation files

### v0.1.0 - Initial Release
- DXF/DWG file upload and parsing
- Symbol detection with 57 known patterns
- AI chat via Claude Sonnet 4
- Dark theme UI
- Docker deployment on Render

## Development Roadmap

### Phase 1: Legend Extraction — Get to 100% [~80-90%]
Fix the legend parsing pipeline so every symbol on the legend sheet is extracted. Currently recovering ~80-90% of symbols — last 10-20% still missed.

- **1A. Page-by-page PDF extraction**: ✅ `pymupdf` splits multi-page PDFs into individual pages, sends each page separately to Claude Vision.
- **1B. Section-aware extraction prompt**: ✅ Pre-scan pass to count sections and symbols per section, then extract per-section with a self-check count target.
- **1C. Bump token budget**: ✅ Increase `max_tokens` from 16384 to 32768 for legend extraction calls.
- **1D. Replace verification pass with reconciliation**: ✅ After merging all pages/sections, reconcile against expected section counts instead of open-ended "find what I missed."
- **1E. Truncation recovery**: ✅ If `stop_reason == "max_tokens"`, retry that page/section with increased budget.
- **1F. Close the last 10-20% gap**: [ ] Investigate why remaining symbols are missed — likely dense/unusual layouts, small text, overlapping entries, or multi-column sections that the vision model skips. Possible approaches: higher-res page crops, overlapping region extraction, structured grid detection, or multi-pass with different prompting strategies.

### Phase 2: Legend Review & Edit UI [x]
Let users verify and correct the AI-extracted legend before processing drawings.

- **2A. Legend review table component**: ✅ `LegendReview.tsx` showing all extracted symbols grouped by category with Code, Name, Category, Shape, SVG Icon columns.
- **2B. Inline editing**: ✅ Click cells to fix codes/names/categories. Add/delete rows for missed or hallucinated entries.
- **2C. Re-parse option**: ✅ "Re-analyze" button to re-run the vision pipeline.
- **2D. Legend persistence**: ✅ `PATCH /api/legends/{id}/symbols` endpoint. Confirmed legend becomes source of truth.
- **2E. Visual confirmation**: ✅ AI-generated SVG icons displayed for quick scan verification.

### Phase 3: Drawing-to-Legend Matching Accuracy [~60%]
Improve how extracted legend symbols get matched to DXF blocks. AI classification with legend constraints (3C) and unmatched block diagnostics (3D) are done. Nearby text integration and fuzzy code matching still needed.

- **3A. Enable single-character code matching**: [ ] Allow single-char legend codes ("S", "H") to match via nearby text labels. Currently filtered out by `len >= 2` requirement in matching pipeline.
- **3B. Improve nearby text → INSERT association**: [ ] `_collect_model_texts()` and adaptive search radius exist in parser.py, but `_NEARBY_LABEL` is never fed into the legend matching pipeline (Strategies 1-6). Need: wire nearby text into matching, add directional bias (text typically right/below symbol), improve clustering.
- **3C. Tighten AI classification with legend constraints**: ✅ Post-processing validation fuzzy-matches AI labels to closest legend entry. Confidence tagging, legend shape/color inheritance all working.
- **3D. Unmatched block diagnostics**: ✅ LEGEND COVERAGE section in Analysis tab shows matched/unmatched legend symbols, per-block strategy trace, AI classification trace.
- **3E. Fuzzy code matching**: [~] Name/description matching works (Strategy 6 word-overlap). Missing: separator normalization (`FM-AIM` ≠ `FMAIM`), subscript handling, Levenshtein distance for close matches.

### Phase 4: Multi-Sheet & Batch Processing [ ]
Support real-world projects with multiple drawing sheets. No project model or batch support exists yet — all storage is single-drawing, in-memory dicts.

- **4A. Project model**: `ProjectData` in models.py containing legend + list of drawings. `project_store` dict in main.py. A project = 1 confirmed legend + N drawings.
- **4B. Batch upload**: New `/api/projects/{id}/upload-drawing` endpoint. Upload multiple DXF/DWG files, process all against the same legend. Progress tracking per file.
- **4C. Aggregated symbol table**: New `/api/projects/{id}/summary` endpoint. Project summary merging counts across all sheets with per-sheet breakdown.
- **4D. Sheet navigation**: Extend sidebar to show sheets within a project, click to switch active drawing without re-uploading.

### Phase 5: Chat & Streaming [ ]
Real-time chat experience with project-wide context.

- **5A. Streaming chat responses**: FastAPI `StreamingResponse` + Anthropic streaming API with SSE. Frontend: incremental text render in ChatPanel.
- **5B. Enhanced chat context**: Once Phase 4 exists, inject aggregated symbol JSON across all sheets into system prompt for project-wide queries.
