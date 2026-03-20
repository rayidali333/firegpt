# FireGPT

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Claude AI](https://img.shields.io/badge/Claude-Opus_4.6_+_Sonnet_4-D97757?logo=anthropic&logoColor=white)](https://anthropic.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)

**Talk to your drawing files.** Upload DXF/DWG construction drawings with optional legend PDFs, automatically detect and count all fire alarm symbols, match them to legend entries with AI-generated SVG icons, visualize them on an interactive floor plan, and chat with the extracted data using AI.

Built for fire alarm contractors who need accurate device counts for pricing bids.

<table>
  <tr>
    <td><img src="https://i.postimg.cc/VshZ9tVn/Screenshot-2026-03-06-at-9-19-06-PM.png" alt="Symbol Detection View" width="420" /></td>
    <td><img src="https://i.postimg.cc/ryd2Lq68/Screenshot-2026-03-06-at-9-23-04-PM.png" alt="Drawing Preview View" width="420" /></td>
  </tr>
  <tr>
    <td align="center"><em>Symbol Detection</em></td>
    <td align="center"><em>Drawing Preview</em></td>
  </tr>
</table>

## How It Works

1. **Upload a Legend** (optional) — drop a PDF or image of the drawing's symbol key. Claude Vision reads every device, its abbreviation, category, and detailed symbol description.
2. **Upload a Drawing** — drop a DXF or DWG file. The app parses all block references (INSERT/MINSERT entities) using `ezdxf`, auto-labels with 57 known patterns, and sends ambiguous blocks to Claude for classification.
3. **AI Matching** — if a legend was uploaded, Claude matches each detected symbol to its legend entry and generates SVG icons from the symbol descriptions.
4. **Visualize** — interactive SVG floor plan with AI-generated device icons at exact symbol positions. Click to highlight, zoom/pan to explore.
5. **Chat** — ask questions like "How many smoke detectors?", "Give me a cost estimate", or "Generate a material takeoff for this bid"

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + ezdxf (gold standard for DXF parsing)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Opus 4.6 (legend extraction) + Claude Sonnet 4 (chat, classification, matching, icon generation) via Anthropic API
- **DWG Support**: LibreDWG (dwg2dxf) + ODA File Converter fallback + ezdxf recovery mode
- **PDF Support**: PyMuPDF for legend PDF→image conversion with adaptive DPI
- **Deployment**: Multi-stage Docker on Render (single container)

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An Anthropic API key (for chat, AI classification, legend extraction, matching, and icon generation)

### Backend

```bash
cd backend
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm start
```

The app will be available at `http://localhost:3000`.

### Docker

```bash
cp backend/.env.example backend/.env
# Edit backend/.env and add your ANTHROPIC_API_KEY
docker compose up --build
```

- Frontend: `http://localhost:3000`
- Backend API: `http://localhost:8000`

## Features

- **Legend extraction** — upload PDF/image legends, Claude Vision extracts all device types with detailed symbol descriptions
- **AI symbol matching** — Claude matches detected DXF symbols to legend entries with confidence scoring
- **SVG icon generation** — AI generates device icons from legend descriptions, rendered at symbol positions
- **57 known symbol patterns** — automatic dictionary matching for common fire alarm abbreviations
- **AI block classification** — Claude classifies ambiguous blocks using full drawing context
- **Interactive SVG preview** — renders DXF geometry with zoom/pan and AI-generated device icon markers
- **Bidirectional highlighting** — click symbols in table ↔ highlights icons on drawing
- **Cost estimation** — AI-powered project estimates with 2024-2025 US market pricing
- **Multi-turn chat** — Claude remembers the full conversation context
- **Manual overrides** — edit counts/labels with audit trail
- **CSV export** — download symbol data for device schedule comparison
- **Symbol consolidation** — merges block variants of same device type into single rows
- **Pipeline loading** — upload → match → icons all complete before showing results
- **Mac OS 9 UI** — classic Platinum aesthetic with beveled borders and traffic light title bar

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/upload` | Upload DXF/DWG → parse + AI classify → return symbols |
| `GET` | `/api/drawings/{id}` | Get parsed data for a drawing |
| `GET` | `/api/drawings/{id}/preview` | Get SVG preview with symbol positions |
| `PATCH` | `/api/drawings/{id}/symbols/{block}` | Override symbol count/label |
| `GET` | `/api/drawings/{id}/export` | Export symbol data as CSV |
| `GET` | `/api/drawings` | List all uploaded drawings |
| `POST` | `/api/chat` | Chat with drawing data |
| `POST` | `/api/legend/upload` | Upload legend PDF/image → AI extract devices |
| `GET` | `/api/legend/{id}` | Get parsed legend data |
| `POST` | `/api/drawings/{id}/match-legend` | Match symbols to legend entries via AI |
| `POST` | `/api/drawings/{id}/generate-icons` | Generate SVG icons for matched symbols |
| `GET` | `/api/icons/{device_name}` | Serve cached SVG icon |

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│                  │     │                  │     │                  │
│  React Frontend  │────▶│  FastAPI Backend  │────▶│  ezdxf Parser    │
│  Upload + Chat   │◀────│  REST API        │◀────│  Block counting  │
│  SVG Preview     │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                │                        │
                   ┌────────────┼────────────┐           │
                   ▼            ▼            ▼           ▼
            ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐
            │Claude Opus │ │ Sonnet 4 │ │ Sonnet 4 │ │ SVG Preview  │
            │Legend Extrc│ │ Chat +   │ │ Matching │ │ Icon Overlay │
            │(Vision API)│ │ Classify │ │ + Icons  │ │              │
            └────────────┘ └──────────┘ └──────────┘ └──────────────┘
```

### Why This Approach Works

- **DXF files** store symbols as "blocks" — reusable templates placed via INSERT entities. Counting INSERT references gives exact symbol counts.
- **ezdxf** is the gold standard Python library for DXF parsing — it reads the file structure directly with near-perfect accuracy.
- **AI classification** handles the long tail — Claude receives full drawing context (layers, legend text, attributes) and classifies blocks that dictionary matching can't identify.
- **Legend matching** enriches data — Claude matches detected symbols to the project's actual legend, replacing generic labels with contractor-specific device names.
- **SVG icons from descriptions** — Claude generates compact SVG icons from legend symbol descriptions, so the drawing view shows recognizable device icons instead of colored dots.
- **Chat is simple** — parsed data is ~2-5KB JSON, injected directly into the LLM system prompt. No vector DB or RAG needed.
- **OCS→WCS recovery** — handles Revit/AutoCAD exports where INSERT coordinates are stored in OCS with mirrored X axis.

## Supported Symbol Types

The parser auto-labels common fire alarm symbols:

| Abbreviation | Symbol |
|-------------|--------|
| SD | Smoke Detector |
| HD | Heat Detector |
| PS | Pull Station |
| HS / H/S | Horn/Strobe |
| DUCT / DD | Duct Detector |
| FACP | Fire Alarm Control Panel |
| NAC | Notification Appliance Circuit |
| SPK | Speaker |
| MON / CM | Monitor/Control Module |

Plus 48 more patterns. Unknown block names are sent to Claude AI for classification. With a legend upload, all symbols get matched to their project-specific names.

## Coming Soon

- **Multi-page Drawing Support** — handle drawing sets with multiple sheets/pages
- **Persistent Storage** — database-backed drawing storage across sessions
- **Project Management** — organize multiple drawings into projects for large bids
- **Device Schedule Comparison** — auto-compare detected symbols against spec sheets
- **Report Generation** — export professional PDF takeoff reports with floor plan markup
- **Team Collaboration** — share drawings and analysis with team members
- **Batch Upload** — upload and process multiple drawings at once

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for all AI features |
| `UPLOAD_DIR` | No | Upload directory (default: ./uploads) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `PORT` | No | Server port (default: 8000) |
