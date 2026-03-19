# FireGPT

## Project Overview

FireGPT is a full-stack web application built for fire alarm contractors. Users upload construction drawings (DXF/DWG format), the app automatically detects and counts all fire alarm symbols (smoke detectors, heat detectors, pull stations, horn/strobes, etc.), renders an interactive SVG preview with color-coded device markers, and provides an AI chat interface powered by Claude to ask questions about the extracted data.

**Tagline**: "Talk to your drawing files"

**Client brief**: Build a tool that lets fire alarm contractors upload CAD drawings, auto-detect all device symbols, get accurate counts, visualize them on the floor plan, and chat with the data for bidding and takeoff purposes.

## Architecture

### Tech Stack
- **Backend**: Python 3.11 + FastAPI + ezdxf (DXF parsing) + ODA File Converter (DWG→DXF)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Opus 4.6 (legend extraction) + Claude Sonnet 4 (chat, block classification) via Anthropic API (async client)
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

## SVG Symbol Icons — Implementation Plan

### Goal
Replace the colored circle markers (in both Symbol Table and Drawing View) with actual SVG icons that look like the real fire alarm symbols from the uploaded legend. The pipeline:

```
Legend PDF → AI extracts descriptions → AI matches to DXF symbols → AI generates SVG icons → Icons replace circles
```

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CURRENT STATE                                │
│                                                                     │
│  DXF Upload ──→ Symbol Detection ──→ Colored Circles (● ● ●)       │
│  Legend Upload ──→ Device Extraction ──→ Table Display (separate)   │
│                        ↕ NO LINK ↕                                  │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                        TARGET STATE                                 │
│                                                                     │
│  DXF Upload ──→ Symbol Detection ──┐                                │
│                                    ├──→ AI Matching ──→ AI SVG Gen  │
│  Legend Upload ──→ Device Extract ─┘         │              │       │
│                                              │              │       │
│                    matched_symbols ◄─────────┘              │       │
│                    svg_icons ◄───────────────────────────────┘       │
│                         │                                           │
│                    ┌────┴────┐                                      │
│                    ▼         ▼                                      │
│              Symbol Table   Drawing View                            │
│              (SVG icons)    (SVG icons at positions)                 │
└─────────────────────────────────────────────────────────────────────┘
```

### Phase 1: AI Matching — Link legend devices to detected DXF symbols

**What**: When both a drawing and legend exist, use Claude to match each detected DXF symbol to its corresponding legend entry. This gives each detected symbol its detailed description and abbreviation from the legend.

**Backend changes**:
- `models.py`: Add `SymbolMatch` model (symbol block_name → legend device name, confidence, reasoning)
- `models.py`: Add `matched_legend` field to `SymbolInfo` (optional `LegendDevice` reference)
- `main.py`: New endpoint `POST /api/drawings/{id}/match-legend` — accepts `legend_id`, runs AI matching, stores results on drawing
- `main.py`: New matching function in a dedicated `matching.py` module
- `matching.py` (new file):
  - `match_symbols_to_legend(symbols, legend_devices)` — sends both lists to Claude
  - Claude sees: detected symbol labels/block_names + legend device names/abbreviations/categories
  - Claude returns: JSON mapping of `{ symbol_label → legend_device_name }` with confidence + reasoning
  - Stores matches on each `SymbolInfo` in `drawings_store`
  - Detailed analysis logging: every match/non-match logged with reasoning

**Frontend changes**:
- `types.ts`: Add `LegendDevice` type, add `matched_legend?: LegendDevice` to `SymbolInfo`
- `api.ts`: Add `matchLegend(drawingId, legendId)` function
- `App.tsx`: Auto-trigger matching when both drawing and legend exist
- `SymbolTable.tsx`: Show match indicator — green check if matched, gray dash if not
- `SymbolTable.tsx`: Show matched legend name + abbreviation in a tooltip or sub-row

**Analysis logging**:
- Log each symbol → legend match with confidence score and reasoning
- Log unmatched symbols (no legend entry found)
- Log unmatched legend entries (in legend but not detected in drawing)
- Log match summary: "Matched 42/45 symbols, 3 unmatched, 8 legend entries unused"

**Testable**: User uploads drawing + legend → sees which symbols matched which legend entries in the Symbols tab and Analysis tab.

---

### Phase 2: SVG Icon Generation — Create icons from descriptions

**What**: For each matched symbol, use Claude to generate compact SVG code from the legend's `symbol_description`. Cache the generated SVGs.

**Backend changes**:
- `icon_gen.py` (new file):
  - `generate_svg_icon(device: LegendDevice) → str` — sends symbol_description to Claude, gets back SVG code
  - Prompt: "Generate a clean, minimal SVG icon (viewBox 0 0 24 24) for this fire alarm symbol: {description}. Return ONLY the SVG markup, no explanation."
  - Validate returned SVG (must contain `<svg` or valid SVG elements)
  - `generate_icons_batch(devices: list[LegendDevice]) → dict[str, str]` — batch generation with progress logging
- `models.py`: Add `svg_icon: str | None = None` to `SymbolInfo`
- `main.py`: New endpoint `POST /api/drawings/{id}/generate-icons` — generates SVG for all matched symbols
- `main.py`: New endpoint `GET /api/icons/{device_name}` — serve cached SVG icon
- In-memory cache: `icons_cache: dict[str, str]` keyed by legend device name → SVG string

**Frontend changes**:
- `types.ts`: Add `svg_icon?: string` to `SymbolInfo`
- `api.ts`: Add `generateIcons(drawingId)` function
- `App.tsx`: Auto-trigger icon generation after matching completes
- `SymbolTable.tsx`: Replace colored dot (●) with inline SVG icon when available
- `LegendTable.tsx`: Show generated SVG icon next to each legend device

**Analysis logging**:
- Log each icon generation: device name, description length, SVG size, generation time
- Log validation results: valid/invalid SVG, retry attempts
- Log batch summary: "Generated 42 icons in 15.3s, 2 failed, 40 cached"

**Testable**: User sees generated SVG icons in the Symbols table and Legend table instead of plain colored dots.

---

### Phase 3: Drawing View Integration — Replace circles with SVG icons

**What**: Modify DrawingViewer to render the generated SVG icons at symbol positions instead of colored circles. Maintain all interactivity.

**Frontend changes**:
- `DrawingViewer.tsx`:
  - Add `<defs>` section with `<symbol>` definitions for each unique icon
  - Default mode: Replace `<circle>` markers with `<use href="#icon-{name}">` elements
  - Scale icons to `markerRadius * 2` (width/height), centered on position
  - Selected mode: Show icon with numbered overlay (keep the numbered text on top)
  - Fallback: Use colored circles for symbols without generated icons
  - Hover: Slight scale-up transform on icon group
  - Click: Same `onSelectSymbol` behavior
- `App.tsx`: Pass `svg_icons` map to DrawingViewer as prop
- `App.css`: Styles for SVG icon markers (hover effects, transitions)

**Interactivity preservation**:
- Click icon → select symbol (same as clicking circle)
- Click selected icon → deselect
- Hover → scale up slightly + cursor pointer
- Selected mode → numbered overlay on top of icon
- Bidirectional: click table row → icons highlight on drawing

**Analysis logging**:
- Log which symbols use icons vs fallback circles
- Log icon rendering stats: total icons, unique icon types, fallback count

**Testable**: Drawing view shows actual fire alarm device icons at the correct positions instead of colored circles. All interactive features (click, hover, select, number) still work.

---

### Data Model Summary (after all phases)

```python
# Backend - models.py additions
class SymbolMatch(BaseModel):
    legend_device_name: str      # Matched legend entry name
    confidence: str              # "high" | "medium" | "low"
    reasoning: str               # Why this match was chosen

class LegendDevice(BaseModel):   # Already exists
    name: str
    abbreviation: str | None
    category: str
    symbol_description: str
    svg_icon: str | None = None  # NEW: generated SVG code

class SymbolInfo(BaseModel):     # Existing, extended
    # ... existing fields ...
    matched_legend: LegendDevice | None = None  # NEW: matched legend entry
    svg_icon: str | None = None                 # NEW: generated SVG icon code
```

```typescript
// Frontend - types.ts additions
interface LegendDevice {
  name: string;
  abbreviation: string | null;
  category: string;
  symbol_description: string;
  svg_icon?: string;           // NEW
}

interface SymbolInfo {
  // ... existing fields ...
  matched_legend?: LegendDevice;  // NEW
  svg_icon?: string;              // NEW
}
```

### API Endpoints (after all phases)

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/drawings/{id}/match-legend` | Match drawing symbols to legend entries (Phase 1) |
| `POST` | `/api/drawings/{id}/generate-icons` | Generate SVG icons for matched symbols (Phase 2) |
| `GET` | `/api/icons/{device_name}` | Get cached SVG icon by device name (Phase 2) |

### Files Modified/Created per Phase

| Phase | Backend | Frontend |
|-------|---------|----------|
| 1 | `matching.py` (new), `models.py`, `main.py` | `types.ts`, `api.ts`, `App.tsx`, `SymbolTable.tsx` |
| 2 | `icon_gen.py` (new), `models.py`, `main.py` | `types.ts`, `api.ts`, `App.tsx`, `SymbolTable.tsx`, `LegendTable.tsx` |
| 3 | — | `DrawingViewer.tsx`, `App.tsx`, `App.css` |

## Change Log

### v2.0.0 - SVG Symbol Icons (In Progress)
- **Legend-to-Drawing Matching**: AI matches detected DXF symbols to uploaded legend entries
- **SVG Icon Generation**: AI generates SVG icons from legend symbol descriptions
- **Icon Rendering**: SVG icons replace colored circles in Symbol Table and Drawing View
- **Opus 4.6**: Legend extraction upgraded to Opus for richer symbol descriptions
- **Adaptive DPI**: PDF rendering DPI auto-selected based on page size (150-400 DPI)
- **Image Tiling**: Dense landscape legends split into overlapping tiles for better Vision accuracy

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
