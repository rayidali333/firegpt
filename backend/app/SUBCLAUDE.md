# Backend App - SUBCLAUDE.md

## Overview

Core FastAPI application module containing all API routes, data models, DXF/DWG parsing engine, SVG preview generation, and Claude AI chat + block classification.

## Files

### main.py - FastAPI Application
- **Routes**: /api/upload, /api/chat, /api/drawings/{id}, /api/drawings/{id}/preview, /api/drawings/{id}/export, PATCH /api/drawings/{id}/symbols/{block}, /api/drawings, /api/health
- **Storage**: Three in-memory stores:
  - `drawings_store`: dict[str, ParseResponse] — parsed drawing data keyed by UUID
  - `file_paths_store`: dict[str, str] — maps drawing_id → DXF file path for preview generation
  - `preview_cache`: dict[str, dict] — cached SVG preview data
- **Upload pipeline**:
  1. Validate file (.dxf/.dwg, max 50MB), save to uploads/
  2. Parse with ezdxf (DXF) or ODA converter + recovery mode (DWG)
  3. AI classification: send ambiguous blocks to Claude with full drawing context
  4. Consolidate: merge block variants of same device type into single rows
  5. Store result and return ParseResponse
- **Symbol consolidation**: Groups symbols by label, combines counts/locations, tracks block variants
- **Manual overrides**: PATCH endpoint lets users edit count/label, tracks original_count
- **CSV export**: Streams symbol data as CSV with confidence/source columns
- **Static serving**: Mounts `./static` for React build, SPA catch-all for client routing
- **CORS**: All origins allowed (development mode)

### models.py - Pydantic Models
- **SymbolInfo**: Represents one detected symbol type
  - block_name (str): CAD block name or combined name with variants
  - label (str): Human-readable name e.g. "Smoke Detector"
  - count (int): Number of instances found
  - locations (list[tuple[float, float]]): ALL insertion coordinates
  - color (str): Category color hex for visualization (#E74C3C for detectors, etc.)
  - confidence (str): "high" (dictionary) | "medium" (AI) | "manual" (user override)
  - source (str): "dictionary" | "ai" | "manual"
  - block_variants (list[str]): Individual block names before consolidation
  - original_count (int|None): Pre-override count for audit
- **AuditEntry**: Classification audit trail — block_name, label, count, method, confidence, matched_term, layers
- **AnalysisStep**: Analysis log entry — type (info/success/warning/error), message
- **ParseResponse**: Full parsing result — drawing_id, filename, file_type, symbols, total_symbols, analysis, audit, xref_warnings, legend_texts
- **ChatHistoryMessage**: role + content for multi-turn chat
- **ChatRequest**: drawing_id + message + history[]
- **ChatResponse**: response string
- **PreviewResponse**: SVG preview — svg, viewBox, width, height, symbol_positions (block_name → [[x,y],...]), position_debug
- **SymbolOverride**: label + count for manual edits

### parser.py - DXF/DWG Parsing Engine
- **57 known fire alarm symbol patterns** in KNOWN_SYMBOLS dict
- **parse_dxf_file(filepath)**: Opens with ezdxf, scans modelspace INSERT/MINSERT entities, groups by block name, records ALL coordinates per block, handles nested blocks, extracts legend text, identifies fire-related layers, builds AI candidate list
- **parse_dwg_file(filepath)**: Tries ODA File Converter first (DWG→DXF), falls back to ezdxf recovery mode
- **_guess_label(block_name)**: Three-tier matching: exact → substring → international patterns
- **_should_skip_block(name)**: Filters AutoCAD system blocks (*, _, ACAD, AcDb, dimension/leader/hatch)
- **_get_symbol_color(label)**: Category-based colors (detectors=red, notification=blue, control=purple, manual=orange, suppression=cyan, infrastructure=gray, safety=green)
- **AI candidate extraction**: Collects full metadata per block — layers, entity_types, attribs, attdef_tags, texts_inside, description — for Claude classification
- Returns ParseResult with symbols sorted by count descending + AI candidates + drawing metadata

### preview.py - SVG Preview Generation
- **generate_drawing_preview(filepath, symbols)**: Main function — renders DXF geometry as SVG, overlays color-coded circle markers at symbol positions
- **DXF geometry rendering**: LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, ELLIPSE, SPLINE, POINT entities converted to SVG paths
- **Symbol position collection** (multi-pass):
  1. `_collect_symbol_positions()`: Direct scan of modelspace INSERT/MINSERT with fuzzy XREF prefix matching via `_match_target_block()`
  2. `_collect_nested_symbol_positions()`: Finds symbols inside container blocks (XREFs, sheet views) — walks block definitions for target blocks
  3. **Recovery pass**: For symbols with 0 positions after schedule removal — uses `entity.ocs().to_wcs()` transform with X-negation fallback for OCS mirrored coordinates
- **Schedule detection** (`_fixup_coordinate_offset()`): Identifies device schedules/legends (positions forming a degenerate line with aspect ratio < 0.02) and removes them
- **Offset correction**: Shifts symbol positions to align with SVG viewBox when there's a systematic offset
- **XREF prefix handling**:
  - `_strip_xref_prefix()`: Removes AutoCAD `$0$`, ODA `|`, BricsCAD backtick prefixes
  - `_match_target_block()`: Multi-level fuzzy matching with `$0$` splits, separator formats, case-insensitive, suffix matching

### chat.py - Claude AI Integration
- **AsyncAnthropic** client for non-blocking requests
- **classify_blocks_with_ai()**: AI-first block classification
  - Sends blocks with full metadata (layers, attribs, entity types, text labels, geometry)
  - Includes drawing context: all block names, all layers, fire-related layers, legend text, already-identified symbols
  - Classification guidelines with standard fire alarm label list
  - Returns dict mapping block_name → label for identified fire devices
- **chat_with_drawing()**: Multi-turn chat with drawing context
  - System prompt: full symbol JSON, filename, cost estimation guidelines (2024-2025 US market rates)
  - Supports full conversation history
- **Model**: claude-sonnet-4-20250514, max_tokens: 4096 (chat), 2048 (classification)

## Data Flow
```
Upload → Save file → Convert DWG if needed → Parse with ezdxf →
Extract INSERTs → Fast-path label with dictionary → Collect AI candidates →
Send ambiguous blocks to Claude → Merge AI labels → Consolidate variants →
Store in memory → Return ParseResponse

Preview → Load DXF → Render geometry as SVG → Collect symbol positions
(direct + nested + OCS recovery) → Filter schedules → Overlay markers →
Cache result → Return PreviewResponse

Chat → Lookup drawing → Build system prompt with symbol JSON + cost guidelines →
Include conversation history → Send to Claude → Return response
```

## Current State
- All endpoints working with full feature set
- Parser handles DXF reliably, DWG via ODA converter + recovery mode
- AI classification functional for ambiguous blocks
- SVG preview with symbol overlay markers working for all device types
- OCS→WCS recovery fixing mirrored coordinates (Revit/AutoCAD exports)
- Chat integration functional with multi-turn history and cost estimation
- Manual overrides and CSV export working
- No persistent storage — data lost on restart
