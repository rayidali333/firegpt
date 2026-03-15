# Backend - SUBCLAUDE.md

## Overview

Python FastAPI backend that handles DXF/DWG file uploads, symbol parsing (dictionary + AI classification), SVG drawing preview generation with symbol overlay, Claude AI chat, and serves the React frontend as static files.

## File Descriptions

### app/main.py
- FastAPI application entry point (version 2.0.0)
- CORS middleware (all origins allowed for dev)
- Routes: /api/upload, /api/upload-legend, /api/chat, /api/drawings, /api/drawings/{id}/preview, /api/drawings/{id}/export, /api/health
- Legend upload endpoint: parses PDF/image legend sheets via Claude Vision
- Direct legend code matching: 5 strategies (sub-group attribs, all attribs, attdef defaults, block internal text, block name segments)
- AI classification pipeline: sends ambiguous blocks to Claude with full drawing context + legend constraints
- Symbol consolidation: merges block variants of same device type into single rows with combined counts
- Legend coverage analysis: reports which legend symbols were/weren't found in the drawing
- Manual override endpoint: PATCH symbol count/label with audit trail
- CSV export endpoint for device schedule comparison
- In-memory stores: `drawings_store`, `file_paths_store`, `preview_cache`, `legend_store`, `drawing_legend_map`
- Static file serving from `./static` directory
- SPA catch-all route for React routing
- File validation: .dxf/.dwg only (max 50MB), legend: .pdf/.png/.jpg/.jpeg/.gif/.webp (max 20MB)

### app/models.py
- **SymbolInfo**: block_name, label, count, locations, color, confidence, source, block_variants, original_count, shape_code, category, legend_code, legend_shape, svg_icon
- **AuditEntry**: block_name, label, count, method (exact/substring/intl/ai/legend_direct/legend_ai), confidence, matched_term, layers
- **AnalysisStep**: type (info/success/warning/error/detail/section), message
- **ParseResponse**: drawing_id (UUID), filename, file_type, symbols list, total_symbols, analysis, audit, xref_warnings, legend_texts
- **ChatHistoryMessage**: role + content for multi-turn conversations
- **ChatRequest**: drawing_id + message + history
- **ChatResponse**: response string from Claude
- **PreviewResponse**: svg, viewBox, width, height, symbol_positions (block_name → [[x,y],...]), position_debug
- **SymbolOverride**: label + count for manual edits
- **LegendSymbol**: code, name, category, shape, shape_code, filled, svg_icon
- **LegendData**: legend_id, filename, symbols list, total_symbols, systems list

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
- `parse_legend_with_vision(image_data, media_type, filename)`: Two-pass legend extraction via Claude Vision + verification pass + SVG icon generation
- `_correct_legend_shape(sym)`: Domain knowledge overrides for AI shape classifications (detectors→hexagon, panels→square, etc.)
- `_generate_symbol_svgs(symbols)`: Batched AI calls to generate SVG icons for each legend symbol
- `_sanitize_svg(svg)`: XSS prevention for AI-generated SVG content
- `classify_blocks_with_ai(...)`: AI block classification — legend-aware or standard mode
- `chat_with_drawing(message, drawing, history, legend)`: Multi-turn chat with full drawing + legend context
- `_build_system_prompt(drawing, legend)`: Injects symbol JSON + legend data + cost estimation guidelines
- Model: claude-sonnet-4-20250514, max_tokens: 4096 (chat), 16384 (classification + legend parsing)

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
- **legend_store**: Parsed legend data keyed by legend_id (in-memory)
- **drawing_legend_map**: drawing_id → legend_id association (in-memory)
- **uploads/**: File system directory for uploaded drawings
- No database configured

## Current State
- All API endpoints functional
- Legend parsing via Claude Vision with two-pass extraction + SVG icon generation
- Parser handles DXF files reliably, DWG via ODA converter + recovery mode
- Direct legend code matching (5 strategies) + AI classification fallback
- Nearby text label scanning associates TEXT entities with INSERT positions
- Sub-grouping: splits blocks by differentiating ATTRIB values (e.g., TYPE=AIM vs TYPE=AOM)
- SVG preview generation with shape-coded symbol overlay markers
- OCS→WCS recovery fixing mirrored coordinates from Revit exports
- Chat integration with Claude Sonnet 4 + multi-turn history + legend context
- Cost estimation with detailed material + labor breakdowns
- Static file serving configured for React build

## Known Issues
- Legend parsing extracts ~80-90/105 symbols on dense legends (single-shot token limit + attention loss)
- No page-level PDF processing for multi-page legends
- Single-character legend codes ("S", "H") skipped by direct matching Strategy 5 (requires len >= 2)
- AI classification sometimes returns labels not in the legend's valid set
