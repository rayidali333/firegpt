# Backend - SUBCLAUDE.md

## Overview

Python FastAPI backend that handles DXF/DWG file uploads, symbol parsing (dictionary + AI classification), SVG drawing preview generation with symbol overlay, Claude AI chat, and serves the React frontend as static files.

## File Descriptions

### app/main.py
- FastAPI application entry point (version 2.0.0)
- CORS middleware (all origins allowed for dev)
- Routes: /api/upload, /api/chat, /api/drawings, /api/drawings/{id}/preview, /api/drawings/{id}/export, /api/health
- Symbol consolidation: merges block variants of same device type into single rows with combined counts
- AI classification pipeline: sends ambiguous blocks to Claude with full drawing context
- Manual override endpoint: PATCH symbol count/label with audit trail
- CSV export endpoint for device schedule comparison
- In-memory stores: `drawings_store` (ParseResponse), `file_paths_store` (DXF paths), `preview_cache` (SVG data)
- Static file serving from `./static` directory
- SPA catch-all route for React routing
- File validation: .dxf/.dwg only, max 50MB

### app/models.py
- **SymbolInfo**: block_name, label, count, locations (all coords), color, confidence, source, block_variants, original_count
- **AuditEntry**: block_name, label, count, method (exact/substring/intl/ai), confidence, matched_term, layers
- **AnalysisStep**: type (info/success/warning/error), message
- **ParseResponse**: drawing_id (UUID), filename, file_type, symbols list, total_symbols, analysis, audit, xref_warnings, legend_texts
- **ChatHistoryMessage**: role + content for multi-turn conversations
- **ChatRequest**: drawing_id + message + history
- **ChatResponse**: response string from Claude
- **PreviewResponse**: svg, viewBox, width, height, symbol_positions (block_name → [[x,y],...]), position_debug
- **SymbolOverride**: label + count for manual edits

### app/parser.py
- Core DXF/DWG parsing engine using ezdxf library
- `parse_dxf_file(filepath)`: Main parser — scans modelspace INSERT/MINSERT entities
- `parse_dwg_file(filepath)`: DWG support via ezdxf recovery mode + ODA File Converter fallback
- `_guess_label(block_name)`: Auto-labels blocks using 57 known fire alarm symbol patterns
- `_should_skip_block(name)`: Filters AutoCAD system blocks (*, _, ACAD, AcDb, etc.)
- `_get_symbol_color(label)`: Returns category-based color for visualization
- AI candidate extraction: collects blocks with full metadata (layers, attribs, entity types, text labels) for Claude classification
- Legend text extraction from MTEXT/TEXT entities in modelspace
- Layer analysis for fire-alarm related naming patterns
- Handles nested blocks (blocks within blocks)
- Returns sorted by count descending

### app/preview.py
- SVG preview generation from DXF files using ezdxf
- `generate_drawing_preview(filepath, symbols)`: Main orchestration function
- Renders DXF geometry: LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, ELLIPSE, SPLINE, POINT
- Symbol position collection with multi-pass approach:
  1. **Direct scan**: Modelspace INSERT/MINSERT entities with fuzzy XREF prefix matching
  2. **Nested scan**: Symbols inside container blocks (XREF, sheet blocks)
  3. **Recovery pass**: OCS→WCS transform with X-negation for mirrored INSERT entities
- Schedule detection: identifies device legends (vertical/horizontal lists) and removes them from floor plan markers
- Offset correction: handles coordinate mismatches between symbol positions and SVG viewBox
- Color-coded circle markers overlaid on SVG at symbol positions
- XREF prefix stripping: AutoCAD `$0$`, ODA `|`, BricsCAD backtick formats
- `_match_target_block()`: Multi-level fuzzy block name matching
- Position debug logging for diagnostics

### app/chat.py
- Claude AI integration using AsyncAnthropic client
- `chat_with_drawing(message, drawing, history)`: Multi-turn chat with full drawing context
- `classify_blocks_with_ai(...)`: AI-first block classification — sends ambiguous blocks with full context
- System prompt includes: full symbol JSON, filename, file type, cost estimation guidelines (2024-2025 US market rates)
- Model: claude-sonnet-4-20250514, max_tokens: 4096 (chat), 2048 (classification)

### Known Symbol Mappings (57 total)
Key patterns: SD (Smoke Detector), HD (Heat Detector), PS (Pull Station), HS/H/S (Horn/Strobe), DUCT/DD (Duct Detector), FACP (Fire Alarm Control Panel), NAC (Notification Appliance Circuit), SPK (Speaker), and 50+ more variations.

## Dependencies (requirements.txt)
- fastapi, uvicorn, python-multipart
- ezdxf (DXF parsing)
- anthropic (Claude API)
- python-dotenv, pydantic

## Storage
- **drawings_store**: In-memory dict, NOT persistent across restarts
- **file_paths_store**: Maps drawing_id → DXF file path (for preview generation)
- **preview_cache**: Cached SVG previews (in-memory)
- **uploads/**: File system directory for uploaded drawings
- No database configured

## Current State
- All API endpoints functional
- Parser handles DXF files reliably, DWG via ODA converter + recovery mode
- AI classification working for ambiguous blocks
- SVG preview generation with symbol overlay markers
- OCS→WCS recovery fixing mirrored coordinates from Revit exports
- Chat integration working with Claude Sonnet 4 + multi-turn history
- Cost estimation with detailed material + labor breakdowns
- Static file serving configured for React build
