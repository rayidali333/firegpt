# Backend - SUBCLAUDE.md

## Overview

Python FastAPI backend that handles DXF/DWG file uploads, symbol parsing (dictionary + AI classification), legend extraction from PDF/images, AI-powered symbol-to-legend matching, SVG icon generation, SVG drawing preview generation with icon overlay, Claude AI chat, and serves the React frontend as static files.

## File Descriptions

### app/main.py
- FastAPI application entry point (version 2.0.0)
- CORS middleware (all origins allowed for dev)
- Routes: upload, chat, drawings, preview, export, legend, matching, icons, health
- Symbol consolidation: merges block variants of same device type into single rows with combined counts
- AI classification pipeline: sends ambiguous blocks to Claude with full drawing context
- Manual override endpoint: PATCH symbol count/label with audit trail
- CSV export endpoint for device schedule comparison
- Legend upload endpoint with file validation and Claude Vision extraction
- Legend matching endpoint: AI matches detected symbols to legend entries
- Icon generation endpoint: AI generates SVG icons for matched symbols
- In-memory stores: `drawings_store`, `legends_store`, `file_paths_store`, `preview_cache`, `icons_cache`
- Static file serving from `./static` directory
- SPA catch-all route for React routing
- File validation: .dxf/.dwg for drawings, .pdf/.png/.jpg/.jpeg/.gif/.webp for legends

### app/models.py
- **SymbolInfo**: block_name, label, count, locations, color, confidence, source, block_variants, original_count, matched_legend (LegendDevice), match_confidence, original_label, svg_icon
- **LegendDevice**: name, abbreviation, category, symbol_description, svg_icon, color
- **LegendParseResponse**: legend_id, filename, devices, categories_found, total_device_types, analysis, notes
- **AuditEntry**: block_name, label, count, method, confidence, matched_term, layers
- **AnalysisStep**: type (info/success/warning/error), message
- **ParseResponse**: drawing_id (UUID), filename, file_type, symbols list, total_symbols, analysis, audit, xref_warnings, legend_texts
- **ChatHistoryMessage**: role + content for multi-turn conversations
- **ChatRequest/ChatResponse**: Chat API models
- **PreviewResponse**: svg, viewBox, width, height, symbol_positions, position_debug
- **SymbolOverride**: label + count for manual edits
- Forward reference resolution: `SymbolInfo.model_rebuild()` for LegendDevice

### app/parser.py
- Core DXF/DWG parsing engine using ezdxf library
- `parse_dxf_file(filepath)`: Main parser — scans modelspace INSERT/MINSERT entities
- `parse_dwg_file(filepath)`: DWG support via LibreDWG (dwg2dxf) + ODA File Converter + ezdxf recovery mode
- `_guess_label(block_name)`: Auto-labels blocks using 57 known fire alarm symbol patterns
- `_should_skip_block(name)`: Filters AutoCAD system blocks (*, _, ACAD, AcDb, etc.)
- `_get_symbol_color(label)`: Returns category-based color for visualization
- AI candidate extraction: collects blocks with full metadata for Claude classification
- Legend text extraction from MTEXT/TEXT entities
- Handles nested blocks and XREF prefixes

### app/preview.py
- SVG preview generation from DXF files using ezdxf
- `generate_drawing_preview(filepath, symbols)`: Main orchestration function
- Renders DXF geometry: LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, ELLIPSE, SPLINE, POINT
- Element cap: 80,000 SVG elements to prevent browser crashes
- Symbol position collection with multi-pass approach:
  1. **Direct scan**: Modelspace INSERT/MINSERT entities with fuzzy XREF prefix matching
  2. **Nested scan**: Symbols inside container blocks (XREF, sheet blocks)
  3. **Recovery pass**: OCS→WCS transform with X-negation for mirrored INSERT entities
- Schedule detection: identifies device legends and removes them from floor plan markers
- XREF prefix stripping: AutoCAD `$0$`, ODA `|`, BricsCAD backtick formats

### app/chat.py
- Claude AI integration using AsyncAnthropic client
- `chat_with_drawing(message, drawing, history)`: Multi-turn chat with full drawing context
- `classify_blocks_with_ai(...)`: AI-first block classification — sends ambiguous blocks with full context
- System prompt includes: full symbol JSON, filename, cost estimation guidelines
- Model: claude-sonnet-4-20250514, max_tokens: 4096 (chat), 2048 (classification)

### app/legend.py
- Legend extraction from PDF/image files using Claude Opus 4.6 Vision
- `parse_legend_file(file_bytes, filename)`: Main entry — validates file, prepares images, calls Claude
- PDF→PNG via PyMuPDF (fitz) with adaptive DPI (150-400 based on page size)
- Image tiling: landscape pages split into overlapping left/right halves for dense legends
- Extracts: name, abbreviation, category, detailed SVG-reproducible symbol_description
- Temperature 0.2 for precise visual descriptions, max 65K output tokens
- Supported formats: PDF, PNG, JPG, JPEG, GIF, WEBP

### app/matching.py
- AI-powered matching of detected DXF symbols to legend entries
- `match_symbols_to_legend(symbols, legend_devices, analysis)`: Sends both lists to Claude
- Claude matches by name/abbreviation/category similarity with reasoning
- Returns mapping with confidence scores (high/medium/low) and detailed reasoning
- Analysis logging: every match decision logged with reasoning

### app/icon_gen.py
- SVG icon generation from legend symbol descriptions using Claude Sonnet 4
- `generate_svg_icon(device_name, symbol_description)`: Generates single icon
- `generate_icons_batch(devices)`: Batch generation with concurrency limit (5 concurrent)
- Icon specs: 24x24 viewBox, stroke-based, currentColor for CSS-driven coloring
- Post-processing: normalizes all colors to currentColor, removes width/height/xmlns
- SVG validation: checks for valid `<svg>` structure
- In-memory cache: `icons_cache[device_name]` → SVG string
- Model: claude-sonnet-4-20250514, temperature 0.2

## Dependencies (requirements.txt)
- fastapi, uvicorn, python-multipart
- ezdxf (DXF parsing)
- anthropic (Claude API — async client)
- python-dotenv, pydantic
- PyMuPDF (PDF→image conversion for legend extraction)

## Storage
- **drawings_store**: In-memory dict (`drawing_id` → `ParseResponse`), NOT persistent across restarts
- **legends_store**: In-memory dict (`legend_id` → `LegendParseResponse`)
- **icons_cache**: In-memory dict (`device_name` → SVG string)
- **file_paths_store**: Maps `drawing_id` → DXF file path (for preview generation)
- **preview_cache**: Cached SVG preview data (in-memory)
- **uploads/**: File system directory for uploaded drawings
- No database configured

## Current State
- All API endpoints functional (upload, chat, preview, export, legend, matching, icons)
- Parser handles DXF files reliably, DWG via LibreDWG/ODA converter + recovery mode
- AI classification working for ambiguous blocks
- SVG preview generation with symbol overlay markers (80K element cap)
- OCS→WCS recovery fixing mirrored coordinates from Revit exports
- Chat integration working with Claude Sonnet 4 + multi-turn history
- Cost estimation with detailed material + labor breakdowns
- Legend extraction working with Claude Opus 4.6 + adaptive DPI + tiling
- Symbol-to-legend matching working with confidence scoring
- SVG icon generation working with batch concurrency and caching
- Static file serving configured for React build
