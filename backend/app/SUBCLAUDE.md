# Backend App - SUBCLAUDE.md

## Overview

Core FastAPI application module containing all API routes, data models, DXF/DWG parsing engine, and Claude AI chat integration.

## Files

### main.py - FastAPI Application
- **Routes**: /api/upload, /api/chat, /api/drawings/{id}, /api/drawings, /api/health
- **Storage**: In-memory `drawings_store` dict (key: UUID string, value: ParseResponse dict)
- **File handling**: Saves uploads to `./uploads/{uuid}.{ext}`, validates .dxf/.dwg, max 50MB
- **Static serving**: Mounts `./static` for React build, SPA catch-all for client routing
- **CORS**: AllowAll origins (development mode)
- **File size config**: `MAX_FILE_SIZE_MB` env var, default 50

### models.py - Pydantic Models
- **SymbolInfo**: Represents one detected symbol type
  - block_name (str): CAD block name e.g. "SD", "HD-24V"
  - label (str): Human-readable name e.g. "Smoke Detector"
  - count (int): Number of instances found
  - sample_locations (list[tuple[float, float]]): First 5 insertion coordinates
- **ParseResponse**: Result of file upload + parsing
  - drawing_id (str): UUID
  - filename (str): Original filename
  - file_type (str): "dxf" or "dwg"
  - symbols (list[SymbolInfo])
  - total_symbols (int): Sum of all counts
- **ChatRequest**: drawing_id + message
- **ChatResponse**: response string

### parser.py - DXF/DWG Parsing Engine
- **57 known fire alarm symbol patterns** in KNOWN_SYMBOLS dict
- **parse_dxf_file(filepath)**: Opens with ezdxf, scans modelspace INSERT entities, groups by block name, records first 5 coordinates per block, handles nested blocks
- **parse_dwg_file(filepath)**: Tries ezdxf recovery mode first, falls back to ODA File Converter if available
- **_guess_label(block_name)**: Matches block names against known patterns (exact match, then substring)
- **_should_skip_block(name)**: Filters AutoCAD system blocks (*, _, ACAD, AcDb, dimension/leader/hatch)
- Returns list sorted by count descending

### chat.py - Claude AI Integration
- **AsyncAnthropic** client for non-blocking requests
- **System prompt**: Injects full symbol data as JSON into Claude's context
- **Model**: claude-sonnet-4-20250514, max_tokens: 1024
- **Role**: Fire alarm contractor assistant - accurate counts, bidding help, symbol identification
- **Context**: filename, file_type, full symbols array with block names, labels, counts, coordinates

## Data Flow
```
Upload → Save file → Parse with ezdxf → Extract INSERTs → Group by block →
Label with known patterns → Store in memory → Return to frontend

Chat → Lookup drawing → Serialize symbol data → Inject into system prompt →
Send to Claude → Return response
```

## Current State
- All endpoints working
- Parser handles DXF reliably
- DWG support via recovery mode (no ODA converter installed on Render)
- Chat integration functional with full context injection
- No persistent storage - data lost on restart
