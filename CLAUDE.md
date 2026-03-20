# FireGPT

## Project Overview

FireGPT is a full-stack web application built for fire alarm contractors. Users upload construction drawings (DXF/DWG format) with optional legend PDFs, the app automatically detects and counts all fire alarm symbols (smoke detectors, heat detectors, pull stations, horn/strobes, etc.), matches them to legend entries, generates SVG device icons, renders an interactive SVG preview with icon markers, and provides an AI chat interface powered by Claude to ask questions about the extracted data.

**Tagline**: "Talk to your drawing files"

**Client brief**: Build a tool that lets fire alarm contractors upload CAD drawings, auto-detect all device symbols, get accurate counts, visualize them on the floor plan, and chat with the data for bidding and takeoff purposes.

## Architecture

### Tech Stack
- **Backend**: Python 3.11 + FastAPI + ezdxf (DXF parsing) + LibreDWG (DWG→DXF) + PyMuPDF (PDF→image)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Opus 4.6 (legend extraction) + Claude Sonnet 4 (chat, block classification, matching, icon generation) via Anthropic API (async client)
- **Deployment**: Multi-stage Docker build on Render
- **No database**: In-memory dictionary storage (drawings_store, legends_store, icons_cache)

### Project Structure
```
/
├── CLAUDE.md                # This file - main project documentation
├── README.md                # Public-facing project documentation
├── Dockerfile               # Multi-stage Docker (Node build + LibreDWG build + Python serve)
├── docker-compose.yml       # Local development orchestration
├── build.sh                 # Render deployment build script
├── render.yaml              # Render platform configuration
├── backend/                 # Python FastAPI backend
│   ├── SUBCLAUDE.md         # Backend-specific documentation
│   ├── app/
│   │   ├── main.py          # FastAPI routes, CORS, static serving, symbol consolidation
│   │   ├── models.py        # Pydantic models (SymbolInfo, LegendDevice, ParseResponse, etc.)
│   │   ├── parser.py        # DXF/DWG parsing engine (57 known symbols + AI classification)
│   │   ├── preview.py       # SVG preview generation with symbol overlay markers
│   │   ├── chat.py          # Claude AI integration (chat + block classification)
│   │   ├── legend.py        # Legend extraction from PDF/images via Claude Vision
│   │   ├── matching.py      # AI-powered symbol-to-legend matching
│   │   └── icon_gen.py      # AI-powered SVG icon generation from descriptions
│   ├── requirements.txt     # Python dependencies
│   └── uploads/             # Uploaded drawing files
└── frontend/                # React TypeScript frontend
    ├── SUBCLAUDE.md          # Frontend-specific documentation
    ├── src/
    │   ├── App.tsx           # Main app - 3-panel layout, upload pipeline orchestration
    │   ├── App.css           # Complete Mac OS 9 Platinum themed stylesheet
    │   ├── index.css         # Global base styles
    │   ├── api.ts            # API client (upload, chat, preview, match, icons, export)
    │   ├── types.ts          # TypeScript interfaces
    │   └── components/
    │       ├── Sidebar.tsx   # Left nav - logo, upload button, file list, view switching
    │       ├── Header.tsx    # Retro window title bar with traffic lights
    │       ├── UploadZone.tsx # Two-step upload: legend (optional) → drawing
    │       ├── SymbolTable.tsx # Symbol results table with legend badges + SVG icons
    │       ├── DrawingViewer.tsx # Interactive SVG floor plan with icon markers
    │       ├── ChatPanel.tsx  # Right-side AI chat with markdown rendering
    │       ├── LegendTable.tsx # Legend device listing with SVG icons
    │       └── AnalysisLog.tsx # Analysis steps and position debug log
    └── package.json
```

## Current State (Latest)

### What's working
- DXF/DWG file upload and parsing via ezdxf
- DWG→DXF conversion via LibreDWG (Docker) or ODA File Converter
- Symbol detection: 57 known patterns (dictionary) + AI classification for ambiguous blocks
- Legend upload: PDF/image legend extraction via Claude Opus 4.6 Vision with adaptive DPI + image tiling
- AI legend matching: detected DXF symbols matched to legend entries with confidence scoring
- SVG icon generation: AI generates device icons from legend symbol descriptions, cached in-memory
- Drawing view: SVG icons replace colored circles at symbol positions (fallback circles for unmatched)
- AI chat via Claude Sonnet 4 with full symbol context injection + multi-turn history
- Interactive SVG drawing preview with zoom/pan
- Bidirectional highlighting between symbol table and drawing view
- OCS→WCS coordinate recovery for INSERT entities with mirrored coordinates (Revit exports)
- Schedule detection: automatically removes device legend/schedule entries from floor plan markers
- XREF prefix handling: AutoCAD `$0$`, ODA `|`, BricsCAD backtick separators
- MINSERT entity support for arrayed block insertions
- Symbol consolidation: merges block variants of same device type into single rows
- Manual count overrides with audit trail
- CSV export of symbol data (via anchor download)
- Cost estimation via AI with 2024-2025 US market pricing
- Mac OS 9 Platinum UI with green desktop, gray windows, classic beveled borders
- Three-panel layout: sidebar navigation | main content (tabs) | AI chat
- Tabbed content: Symbols table, Drawing view, Analysis log, Legend table
- Two-step upload flow: legend (optional) → drawing, with full pipeline loading
- Docker deployment on Render
- Static file serving (React build served by FastAPI)

### Design System
The UI uses a Mac OS 9 Platinum aesthetic:
- **Color palette**: Green desktop (#3B9B4A), gray windows (#DDDDDD), white content area, blue accent (#336699)
- **Window chrome**: Classic title bar with traffic light buttons (red/yellow/green)
- **Typography**: Lucida Grande, Geneva, system fonts; Monaco monospace
- **Borders**: Classic 3D beveled effects (light top-left, dark bottom-right)
- **Layout**: Three-panel (sidebar 200px | flexible content | chat 340px)
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
| `POST` | `/api/legend/upload` | Upload legend PDF/image → AI extract devices → return LegendParseResponse |
| `GET` | `/api/legend/{id}` | Retrieve cached legend data |
| `POST` | `/api/drawings/{id}/match-legend` | Match drawing symbols to legend entries via AI |
| `POST` | `/api/drawings/{id}/generate-icons` | Generate SVG icons for matched symbols |
| `GET` | `/api/icons/{device_name}` | Serve cached SVG icon by device name |
| `GET` | `/{path}` | SPA catch-all (serves React index.html) |

## Data Flow

```
1. User optionally uploads legend PDF/image
2. Claude Vision extracts device names, abbreviations, categories, symbol descriptions
3. User uploads DXF/DWG drawing (drag-drop or browse)
4. Backend saves file, converts DWG→DXF if needed (LibreDWG or ODA)
5. Parser scans INSERT/MINSERT entities, groups by block name
6. Fast-path: auto-labels using 57 known fire alarm symbol patterns
7. AI-path: sends ambiguous blocks to Claude with full drawing context for classification
8. Consolidates block variants of same device type into single rows
9. If legend exists: AI matches detected symbols to legend entries
10. If matched: AI generates SVG icons from legend symbol descriptions
11. Frontend receives fully enriched data (symbols + matches + icons)
12. Frontend displays symbol table with SVG icons and legend badges
13. Drawing preview: renders DXF geometry as SVG, overlays SVG icon markers
14. Symbol positions recovered via OCS→WCS transforms, schedule filtering, X-negation
15. User asks questions in right-side chat panel
16. Backend injects full symbol JSON into Claude system prompt
17. Claude responds with accurate counts, cost estimates, and analysis
```

## Key Design Decisions

1. **No database** - In-memory dict storage. Drawings are transient per session. Keeps deployment simple.
2. **AI-first classification** - Dictionary matching for known patterns, Claude AI for everything else. Handles any naming convention.
3. **Legend as source of truth** - When matched, legend device names replace dictionary/AI labels. Legend provides the canonical naming.
4. **Direct prompt injection** - All symbol data (<5KB JSON) goes into Claude's system prompt. No RAG needed at this scale.
5. **DXF as source of truth** - Counts INSERT entities (block insertions), not pixel analysis. Industry-standard accuracy.
6. **OCS→WCS recovery** - Handles Revit/AutoCAD exports where INSERT coordinates are stored in OCS with mirrored X axis.
7. **Pipeline loading** - Upload → match → icons all complete before showing results. No flash of incomplete data.
8. **SVG icon pipeline** - Legend descriptions → Claude generates SVG icons → `<symbol>`/`<use>` for efficient rendering at scale.
9. **Multi-stage Docker** - Single container: Node builds React, LibreDWG compiles, Python serves API + static files.
10. **Mac OS 9 UI** - Classic Platinum aesthetic that stands out from typical dark-mode dev tools. Inviting for contractors.
11. **Always-visible chat** - Chat panel is always shown (Cursor-style), disabled state when no drawing loaded.
12. **Symbol consolidation** - Different block names mapping to same device type merged into single rows for contractor clarity.

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
| `ANTHROPIC_API_KEY` | Yes | Claude API key for chat, classification, legend extraction, matching, and icon generation |
| `UPLOAD_DIR` | No | Upload directory (default: ./uploads) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `PORT` | No | Server port (default: 8000, Render sets automatically) |

## Change Log

### v2.0.0 - SVG Symbol Icons
- **Legend Upload**: Two-step upload flow — optional legend PDF/image before drawing upload
- **Legend Extraction**: Claude Opus 4.6 Vision extracts device names, abbreviations, categories, and detailed symbol descriptions
- **Adaptive DPI**: PDF rendering DPI auto-selected based on page size (150-400 DPI)
- **Image Tiling**: Dense landscape legends split into overlapping tiles for better Vision accuracy
- **Legend-to-Drawing Matching**: AI matches detected DXF symbols to uploaded legend entries with confidence scoring
- **Legend as Source of Truth**: Matched legend names replace dictionary/AI labels; original labels preserved for audit
- **SVG Icon Generation**: AI generates compact SVG icons (24x24 viewBox) from legend symbol descriptions
- **Icon Rendering (Drawing View)**: SVG icons replace colored circles at symbol positions via `<symbol>`/`<use>` pattern
- **Icon Rendering (Symbol Table)**: Inline SVG icons in symbol table and legend table
- **Selected Mode Icons**: Numbered badge overlay on icons when symbol selected in drawing view
- **Icon Fallback**: Colored circles used for symbols without generated icons
- **Pipeline Loading**: Upload → match → icons all complete before revealing results to user
- **CSV Export Fix**: Uses anchor download instead of window.open (prevented popup blocking)
- **Preview Fix**: Preview useEffect depends on drawingId only, preventing redundant re-fetches on symbol updates
- **Upload UI**: Properly centered two-step upload with Mac OS 9 Platinum styling

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
- Classic inset/raised border effects
- Added CLAUDE.md and SUBCLAUDE.md documentation files

### v0.1.0 - Initial Release
- DXF/DWG file upload and parsing
- Symbol detection with 57 known patterns
- AI chat via Claude Sonnet 4
- Dark theme UI
- Docker deployment on Render
