# Backend - SUBCLAUDE.md

## Overview

Python FastAPI backend that handles DXF/DWG file uploads, symbol parsing, Claude AI chat, and serves the React frontend as static files.

## File Descriptions

### app/main.py
- FastAPI application entry point
- CORS middleware (all origins allowed for dev)
- Routes: /api/upload, /api/chat, /api/drawings, /api/health
- In-memory `drawings_store` dict keyed by UUID
- Static file serving from `./static` directory
- SPA catch-all route for React routing
- File validation: .dxf/.dwg only, max 50MB

### app/models.py
- **SymbolInfo**: block_name, label, count, sample_locations (first 5 coords)
- **ParseResponse**: drawing_id (UUID), filename, file_type, symbols list, total_symbols
- **ChatRequest**: drawing_id + message string
- **ChatResponse**: response string from Claude

### app/parser.py
- Core DXF/DWG parsing engine using ezdxf library
- `parse_dxf_file(filepath)`: Main parser - scans modelspace INSERT entities
- `parse_dwg_file(filepath)`: DWG support with ezdxf recovery mode + ODA converter fallback
- `_guess_label(block_name)`: Auto-labels blocks using 57 known fire alarm symbol patterns
- `_should_skip_block(name)`: Filters AutoCAD system blocks (*, _, ACAD, AcDb, etc.)
- Handles nested blocks (blocks within blocks)
- Returns sorted by count descending

### app/chat.py
- Claude AI integration using AsyncAnthropic client
- `chat_with_drawing(drawing_data, message)`: Main chat function
- System prompt includes: full symbol JSON, filename, file type, role instructions
- Model: claude-sonnet-4-20250514 with 1024 max tokens
- Instructions tell Claude to act as fire alarm contractor assistant
- Accurate counts, bidding help, symbol identification

### Known Symbol Mappings (57 total)
Key patterns: SD (Smoke Detector), HD (Heat Detector), PS (Pull Station), HS/H/S (Horn/Strobe), DUCT/DD (Duct Detector), FACP (Fire Alarm Control Panel), NAC (Notification Appliance Circuit), and 50+ more variations including manufacturer-specific block names.

## Dependencies (requirements.txt)
- fastapi==0.115.6
- uvicorn[standard]==0.34.0
- python-multipart==0.0.20
- ezdxf==1.4.2
- anthropic==0.44.0
- python-dotenv==1.0.1
- pydantic==2.10.4

## Storage
- **drawings_store**: In-memory dict, NOT persistent across restarts
- **uploads/**: File system directory for uploaded drawings
- No database configured

## Current State
- All API endpoints functional
- Parser handles DXF files reliably, DWG via recovery mode
- Chat integration working with Claude Sonnet 4
- Static file serving configured for React build
- CORS enabled for all origins
