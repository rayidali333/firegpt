# FireGPT

## Project Overview

FireGPT is a full-stack web application built for fire alarm contractors. Users upload construction drawings (DXF/DWG format), the app automatically detects and counts all fire alarm symbols (smoke detectors, heat detectors, pull stations, horn/strobes, etc.), and provides an AI chat interface powered by Claude to ask questions about the extracted data.

**Client brief**: Build a tool that lets fire alarm contractors upload CAD drawings, auto-detect all device symbols, get accurate counts, and chat with the data for bidding and takeoff purposes.

## Architecture

### Tech Stack
- **Backend**: Python 3.11 + FastAPI + ezdxf (DXF parsing)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Sonnet 4 via Anthropic API (async client)
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
│   │   ├── main.py          # FastAPI routes, CORS, static serving
│   │   ├── models.py        # Pydantic models (SymbolInfo, ParseResponse, etc.)
│   │   ├── parser.py        # DXF/DWG parsing engine (57 known symbols)
│   │   └── chat.py          # Claude AI integration (system prompt injection)
│   ├── requirements.txt     # Python dependencies
│   └── uploads/             # Uploaded drawing files
└── frontend/                # React TypeScript frontend
    ├── SUBCLAUDE.md          # Frontend-specific documentation
    ├── src/
    │   ├── App.tsx           # Main app - 3-panel layout (sidebar | content | chat)
    │   ├── App.css           # Complete retro Mac OS themed stylesheet
    │   ├── index.css         # Global base styles
    │   ├── api.ts            # API client (uploadDrawing, chatWithDrawing)
    │   ├── types.ts          # TypeScript interfaces
    │   └── components/
    │       ├── Sidebar.tsx   # Left nav - logo, upload button, file list
    │       ├── Header.tsx    # Retro window title bar with traffic lights
    │       ├── UploadZone.tsx # Drag-drop file upload (center panel)
    │       ├── SymbolTable.tsx # Symbol detection results table
    │       └── ChatPanel.tsx  # Right-side AI chat (Cursor-style)
    └── package.json
```

## Current State (Latest)

### What's working
- DXF/DWG file upload and parsing via ezdxf
- Symbol detection with 57 known fire alarm symbol mappings
- AI chat via Claude Sonnet 4 with full symbol context injection
- Retro Mac OS vintage UI design with warm cream/beige palette
- Three-panel layout: sidebar navigation | main content | AI chat
- Cursor-style AI chat panel on the right side
- Classic window chrome with traffic light buttons
- Docker deployment on Render
- Static file serving (React build served by FastAPI)

### Design System
The UI replicates the classic Mac OS 9 Platinum aesthetic:
- **Color palette**: Green desktop (#3B9B4A), gray window (#DDDDDD), white content areas
- **Window chrome**: Classic 3D beveled borders, title bar with filled/outline dots (close/minimize/zoom)
- **3D borders**: Raised borders (white top-left, gray bottom-right), sunken panels for content areas
- **Typography**: Lucida Grande/Geneva system fonts, Monaco monospace, 12px base
- **Layout**: Three-panel (sidebar 200px | flexible content | chat 320px)
- **Scrollbars**: Classic Mac OS wide scrollbars with button arrows and striped tracks
- **Responsive**: Stacks vertically on mobile (<900px)

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/upload` | Upload DXF/DWG → parse symbols → return ParseResponse |
| `GET` | `/api/drawings/{id}` | Retrieve cached drawing data by UUID |
| `GET` | `/api/drawings` | List all uploaded drawings |
| `POST` | `/api/chat` | Send message + drawing_id → Claude response |
| `GET` | `/{path}` | SPA catch-all (serves React index.html) |

## Data Flow

```
1. User uploads DXF/DWG file (drag-drop or browse)
2. Backend saves file, parses with ezdxf
3. Parser scans INSERT entities, groups by block name
4. Auto-labels using 57 known fire alarm symbol patterns
5. Returns ParseResponse with symbols + counts
6. Frontend displays symbol table in center panel
7. User asks questions in right-side chat panel
8. Backend injects full symbol JSON into Claude system prompt
9. Claude responds with accurate counts and analysis
10. Chat continues with full drawing context
```

## Key Design Decisions

1. **No database** - In-memory dict storage. Drawings are transient per session. Keeps deployment simple.
2. **Direct prompt injection** - All symbol data (<5KB JSON) goes into Claude's system prompt. No RAG needed at this scale.
3. **DXF as source of truth** - Counts INSERT entities (block insertions), not pixel analysis. Industry-standard accuracy.
4. **Multi-stage Docker** - Single container: Node builds React, Python serves API + static files.
5. **Retro UI** - Warm, distinctive aesthetic that stands out from typical dark-mode dev tools. Inviting for contractors.
6. **Always-visible chat** - Chat panel is always shown (Cursor-style), disabled state when no drawing loaded.
7. **Sidebar navigation** - Persistent left sidebar for branding, upload, and file management.

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
| `ANTHROPIC_API_KEY` | Yes | Claude API key for chat functionality |
| `UPLOAD_DIR` | No | Upload directory (default: ./uploads) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `PORT` | No | Server port (default: 8000, Render sets automatically) |

## Change Log

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
