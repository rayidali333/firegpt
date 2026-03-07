# FireGPT

[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://python.org)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)](https://react.dev)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Claude AI](https://img.shields.io/badge/Claude-Sonnet_4-D97757?logo=anthropic&logoColor=white)](https://anthropic.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?logo=docker&logoColor=white)](https://docker.com)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Talk to your drawing files.** Upload DXF/DWG construction drawings, automatically detect and count all fire alarm symbols, visualize them on an interactive floor plan, and chat with the extracted data using AI.

Built for fire alarm contractors who need accurate device counts for pricing bids.

<p align="center">
  <img src="https://i.postimg.cc/VshZ9tVn/Screenshot-2026-03-06-at-9-19-06-PM.png" alt="Symbol Detection View" width="420" />
  &nbsp;&nbsp;
  <img src="https://i.postimg.cc/ryd2Lq68/Screenshot-2026-03-06-at-9-23-04-PM.png" alt="Drawing Preview View" width="420" />
</p>

## How It Works

1. **Upload** a DXF or DWG construction drawing (drag-drop or browse)
2. **Auto-detect** — the app parses all block references (INSERT/MINSERT entities) using `ezdxf`, auto-labels with 57 known patterns, and sends ambiguous blocks to Claude AI for classification
3. **Visualize** — interactive SVG preview of the floor plan with color-coded device markers and bidirectional highlighting
4. **Review** — see a complete symbol table with counts, confidence levels, and block variants
5. **Chat** — ask questions like "How many smoke detectors?", "Give me a cost estimate", or "Generate a device schedule for this bid"

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + ezdxf (gold standard for DXF parsing)
- **Frontend**: React 19 + TypeScript + Lucide Icons
- **AI**: Claude Sonnet 4 via Anthropic API — powers both chat AND automatic block classification
- **DWG Support**: ODA File Converter (converts DWG→DXF) + ezdxf recovery mode fallback
- **Deployment**: Multi-stage Docker on Render (single container)

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An Anthropic API key (for chat and AI classification)

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

- **57 known symbol patterns** — automatic dictionary matching for common fire alarm abbreviations
- **AI block classification** — Claude classifies ambiguous blocks using full drawing context
- **Interactive SVG preview** — renders DXF geometry with zoom/pan and color-coded device markers
- **Bidirectional highlighting** — click symbols in table ↔ highlights markers on drawing
- **Cost estimation** — AI-powered project estimates with 2024-2025 US market pricing
- **Multi-turn chat** — Claude remembers the full conversation context
- **Manual overrides** — edit counts/labels with audit trail
- **CSV export** — download symbol data for device schedule comparison
- **Symbol consolidation** — merges block variants of same device type into single rows

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
| `POST` | `/api/chat` | Chat with drawing data (drawing_id + message + history) |

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│                  │     │                  │     │                  │
│  React Frontend  │────▶│  FastAPI Backend  │────▶│  ezdxf Parser    │
│  Upload + Chat   │◀────│  REST API        │◀────│  Block counting  │
│  SVG Preview     │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                │                        │
                                ▼                        ▼
                         ┌──────────────────┐     ┌──────────────────┐
                         │  Claude API      │     │  SVG Preview     │
                         │  Chat + Classify │     │  Symbol Overlay  │
                         └──────────────────┘     └──────────────────┘
```

### Why This Approach Works

- **DXF files** store symbols as "blocks" — reusable templates placed via INSERT entities. Counting INSERT references gives exact symbol counts.
- **ezdxf** is the gold standard Python library for DXF parsing — it reads the file structure directly with near-perfect accuracy.
- **AI classification** handles the long tail — Claude receives full drawing context (layers, legend text, attributes) and classifies blocks that dictionary matching can't identify.
- **Chat is simple** — parsed data is ~2-5KB JSON, injected directly into the LLM system prompt. No vector DB or RAG needed.
- **OCS→WCS recovery** — handles Revit/AutoCAD exports where INSERT coordinates are stored in OCS with mirrored X axis, ensuring all device types show markers on the floor plan.

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

Plus 48 more patterns. Unknown block names are sent to Claude AI for classification.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | Yes | Claude API key for chat and AI classification |
| `UPLOAD_DIR` | No | Upload directory (default: ./uploads) |
| `MAX_FILE_SIZE_MB` | No | Max upload size in MB (default: 50) |
| `PORT` | No | Server port (default: 8000) |

## License

MIT
