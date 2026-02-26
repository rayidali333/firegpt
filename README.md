# DrawingIQ

ChatGPT for construction drawings. Upload DXF/DWG fire alarm drawings, automatically detect and count all symbols (smoke detectors, heat detectors, pull stations, etc.), and chat with the extracted data using AI.

Built for fire alarm contractors who need accurate device counts for pricing bids.

## How It Works

1. **Upload** a DXF or DWG construction drawing
2. **Auto-detect** — the app parses all block references (INSERT entities) using `ezdxf` and counts every symbol
3. **Review** — see a complete symbol table with counts, block names, and labels
4. **Chat** — ask questions like "How many smoke detectors?" or "Give me a full device schedule for this bid"

## Tech Stack

- **Backend**: Python 3.11 + FastAPI + ezdxf (gold standard for DXF parsing)
- **Frontend**: React 18 + TypeScript
- **Chat**: Claude API with direct prompt injection (no RAG needed — parsed data is tiny)
- **DWG Support**: ODA File Converter (optional, for .dwg files)

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- An Anthropic API key (for the chat feature)

### Backend

```bash
cd backend
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY
pip install -r requirements.txt
python run.py
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

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/health` | Health check |
| `POST` | `/api/upload` | Upload a DXF/DWG file, returns parsed symbol data |
| `GET` | `/api/drawings/{id}` | Get parsed data for a drawing |
| `GET` | `/api/drawings` | List all uploaded drawings |
| `POST` | `/api/chat` | Chat with drawing data (requires `drawing_id` + `message`) |

## Architecture

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────┐
│                  │     │                  │     │                  │
│  React Frontend  │────▶│  FastAPI Backend  │────▶│  ezdxf Parser    │
│  Upload + Chat   │◀────│  REST API        │◀────│  Block counting  │
│                  │     │                  │     │                  │
└──────────────────┘     └──────────────────┘     └──────────────────┘
                                │
                                ▼
                         ┌──────────────────┐
                         │  Claude API      │
                         │  Chat with data  │
                         └──────────────────┘
```

### Why This Approach Works

- **DXF files** store symbols as "blocks" — reusable templates placed via INSERT entities. Counting INSERT references gives exact symbol counts.
- **ezdxf** is the gold standard Python library for DXF parsing — it reads the file structure directly with near-perfect accuracy.
- **Chat is simple** — parsed data is ~2-5KB JSON, injected directly into the LLM system prompt. No vector DB or RAG needed.

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
| SPK | Sprinkler |
| MON / CM | Monitor/Control Module |

Unknown block names are displayed as-is so users can identify them.
