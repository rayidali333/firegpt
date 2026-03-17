import csv
import io
import json
import logging
import os
import re
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from app.parser import parse_dxf_file, parse_dwg_file, _get_symbol_color, get_category_color, get_symbol_palette_color
from app.preview import generate_drawing_preview
from app.chat import chat_with_drawing, chat_with_drawing_stream, classify_blocks_with_ai, parse_legend_with_vision, parse_drawing_pdf_with_vision

logger = logging.getLogger(__name__)

# Configure logging to show detailed output
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
from app.models import (
    AnalysisStep, AuditEntry, ChatRequest, ChatResponse, LegendData, LegendSymbol,
    ParseResponse, PreviewResponse, ProjectChatRequest, ProjectData,
    ProjectDrawingInfo, ProjectSummary, SymbolInfo, SymbolOverride,
)

load_dotenv()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "./uploads"))
MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "50"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# React build directory (built during deploy)
STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="FireGPT", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory store for parsed drawings (use a DB in production)
drawings_store: dict[str, ParseResponse] = {}
# Store file paths for preview generation — always points to a readable DXF
file_paths_store: dict[str, str] = {}
# Cache generated previews
preview_cache: dict[str, dict] = {}
# Legend store — parsed legend data keyed by legend_id
legend_store: dict[str, LegendData] = {}
# Track which legend is associated with which drawing
drawing_legend_map: dict[str, str] = {}  # drawing_id → legend_id
# Project store — groups a legend + multiple drawings
project_store: dict[str, ProjectData] = {}
# Track which project a drawing belongs to
drawing_project_map: dict[str, str] = {}  # drawing_id → project_id


# ── Non-device block patterns for pre-classification filtering ──
# Blocks matching these patterns are architectural/structural/furniture/plumbing
# elements that should never be classified as fire alarm devices.
_NON_DEVICE_BLOCK_PATTERNS = [
    re.compile(r"(?i)^Grid\b"),                    # Structural grid markers (column grids)
    re.compile(r"(?i)^IP-LND-"),                   # Project XREF references (arch/struct/ID)
    re.compile(r"(?i)^AR-"),                        # Architectural blocks (doors, walls, columns)
    re.compile(r"(?i)^ST-"),                        # Structural blocks
    re.compile(r"(?i)^Railing\b"),                  # Railings
    re.compile(r"(?i)^Chair\b"),                    # Furniture
    re.compile(r"(?i)^Sofa\b"),                     # Furniture
    re.compile(r"(?i)^Table\b"),                    # Furniture
    re.compile(r"(?i)^Credenza\b"),                 # Furniture
    re.compile(r"(?i)^Walls\b"),                    # Wall geometry blocks
    re.compile(r"(?i)^Window\b"),                   # Windows
    re.compile(r"(?i)^Door\b"),                     # Doors
    re.compile(r"(?i)^Floor Drain\b"),              # Plumbing
    re.compile(r"(?i)^Urinal\b"),                   # Plumbing
    re.compile(r"(?i)^Sink\b"),                     # Plumbing
    re.compile(r"(?i)^WCPan\b"),                    # Plumbing
    re.compile(r"(?i)^Sanitary\b"),                 # Sanitary fixtures
    re.compile(r"(?i)^COTTO\b"),                    # Bathroom accessories brand
    re.compile(r"(?i)^Mediclinics\b"),              # Dispensers brand
    re.compile(r"(?i)^Top Rail\b"),                 # Railing components
    re.compile(r"(?i)^NBS_EscpRtSgns\b"),           # Evacuation route signs (not fire alarm devices)
    re.compile(r"(?i)^Furniture\b"),                # Generic furniture
    re.compile(r"(?i)^Lab Stool\b"),               # Furniture
    re.compile(r"(?i)^Printer\b"),                 # Office equipment
    re.compile(r"(?i)^Electrical Equipment\b"),     # Generic electrical
]


# ── Fuzzy matching utilities for Phase 3E ──

def _normalize_code(code: str) -> str:
    """Strip separators (-_. /()) and uppercase for fuzzy comparison.

    Handles: FM-AIM → FMAIM, SMOKE_DETECTOR → SMOKEDETECTOR, etc.
    """
    return re.sub(r'[-_.\s/()]+', '', code).upper()


def _levenshtein_distance(s1: str, s2: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)

    prev_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr_row.append(min(
                curr_row[j] + 1,        # insert
                prev_row[j + 1] + 1,    # delete
                prev_row[j] + cost,     # substitute
            ))
        prev_row = curr_row

    return prev_row[-1]


def _fuzzy_legend_lookup(
    value: str,
    legend_code_lookup: dict[str, "LegendSymbol"],
) -> tuple["LegendSymbol | None", str]:
    """Try to match a value against legend codes using fuzzy strategies.

    Returns (matched_symbol, match_description) or (None, "").
    Strategies tried in order:
    1. Exact match (already done upstream, but included for completeness)
    2. Separator-normalized match (FM-AIM == FMAIM)
    3. Levenshtein distance (edit distance <= 1 for codes <= 4 chars, <= 2 for longer)
    """
    val_upper = value.upper().strip()

    # 1. Exact (already checked upstream, skip)

    # 2. Separator-normalized match
    val_norm = _normalize_code(val_upper)
    if len(val_norm) >= 2:  # Only for non-trivial codes
        for code, sym in legend_code_lookup.items():
            if _normalize_code(code) == val_norm:
                return sym, f"separator_normalized({value}→{val_norm}={code})"

    # 3. Levenshtein distance for close matches
    # Require minimum 3 chars to avoid false positives with short generic prefixes
    # like IT~IP, AC~BC, etc. that appear in Revit block naming conventions.
    if len(val_upper) >= 3:
        max_dist = 1 if len(val_upper) <= 4 else 2
        best_match = None
        best_dist = max_dist + 1
        best_code = ""
        for code, sym in legend_code_lookup.items():
            # Only compare codes of similar length (within ±2)
            if abs(len(code) - len(val_upper)) > max_dist:
                continue
            dist = _levenshtein_distance(val_upper, code)
            if dist <= max_dist and dist < best_dist:
                best_dist = dist
                best_match = sym
                best_code = code
        if best_match:
            return best_match, f"levenshtein({value}~{best_code}, dist={best_dist})"

    return None, ""


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload-legend", response_model=LegendData)
async def upload_legend(file: UploadFile):
    """Upload a legend/key sheet (PDF or image) and parse it with Claude Vision."""
    logger.info("=== LEGEND UPLOAD START ===")
    logger.info(f"Filename: {file.filename}, Content-Type: {file.content_type}")

    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if ext not in allowed_exts:
        msg = f"Unsupported file type: {ext}. Legend must be an image ({', '.join(allowed_exts)})."
        logger.error(f"Legend rejected: {msg}")
        raise HTTPException(400, msg)

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    logger.info(f"File size: {size_mb:.2f} MB, extension: {ext}")

    if size_mb > 20:
        raise HTTPException(400, f"File too large ({size_mb:.1f}MB). Max legend size is 20MB.")

    # Map file extension to media type
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    media_type = media_types.get(ext, "image/png")
    logger.info(f"Media type resolved: {media_type}")

    try:
        logger.info("Calling parse_legend_with_vision...")
        legend_data = await parse_legend_with_vision(
            image_data=contents,
            media_type=media_type,
            filename=file.filename,
        )
        logger.info(
            f"Legend parsed successfully: {legend_data.total_symbols} symbols, "
            f"legend_id={legend_data.legend_id}"
        )
    except Exception as e:
        logger.error(f"Legend parsing failed: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        raise HTTPException(500, f"Failed to parse legend: {type(e).__name__}: {str(e)}")

    legend_store[legend_data.legend_id] = legend_data
    logger.info("=== LEGEND UPLOAD COMPLETE ===")
    return legend_data


@app.get("/api/legends/{legend_id}", response_model=LegendData)
async def get_legend(legend_id: str):
    """Retrieve a specific legend by ID."""
    if legend_id not in legend_store:
        raise HTTPException(404, "Legend not found")
    return legend_store[legend_id]


@app.patch("/api/legends/{legend_id}/symbols/{symbol_idx}")
async def update_legend_symbol(legend_id: str, symbol_idx: int, update: dict):
    """Update a specific legend symbol by its index.

    Accepts partial updates — only provided fields are changed.
    Valid fields: code, name, category, shape, shape_code, filled.
    """
    if legend_id not in legend_store:
        raise HTTPException(404, "Legend not found")

    legend = legend_store[legend_id]
    if symbol_idx < 0 or symbol_idx >= len(legend.symbols):
        raise HTTPException(404, f"Symbol index {symbol_idx} out of range (0-{len(legend.symbols)-1})")

    sym = legend.symbols[symbol_idx]
    allowed_fields = {"code", "name", "category", "shape", "shape_code", "filled"}
    for field, value in update.items():
        if field in allowed_fields:
            setattr(sym, field, value)

    logger.info(f"Legend {legend_id}: updated symbol [{symbol_idx}] → code={sym.code!r}, name={sym.name!r}")
    return {"status": "ok", "symbol": sym.model_dump()}


@app.post("/api/legends/{legend_id}/symbols")
async def add_legend_symbol(legend_id: str, symbol: LegendSymbol):
    """Add a new symbol to a legend."""
    if legend_id not in legend_store:
        raise HTTPException(404, "Legend not found")

    legend = legend_store[legend_id]
    legend.symbols.append(symbol)
    legend.total_symbols = len(legend.symbols)

    # Update systems list if new category
    if symbol.category and symbol.category not in legend.systems:
        legend.systems.append(symbol.category)

    logger.info(f"Legend {legend_id}: added symbol code={symbol.code!r}, name={symbol.name!r}")
    return {"status": "ok", "index": len(legend.symbols) - 1, "symbol": symbol.model_dump()}


@app.delete("/api/legends/{legend_id}/symbols/{symbol_idx}")
async def delete_legend_symbol(legend_id: str, symbol_idx: int):
    """Delete a symbol from a legend by its index."""
    if legend_id not in legend_store:
        raise HTTPException(404, "Legend not found")

    legend = legend_store[legend_id]
    if symbol_idx < 0 or symbol_idx >= len(legend.symbols):
        raise HTTPException(404, f"Symbol index {symbol_idx} out of range")

    removed = legend.symbols.pop(symbol_idx)
    legend.total_symbols = len(legend.symbols)

    logger.info(f"Legend {legend_id}: deleted symbol [{symbol_idx}] code={removed.code!r}")
    return {"status": "ok", "removed": removed.model_dump()}


@app.put("/api/legends/{legend_id}/symbols")
async def replace_all_legend_symbols(legend_id: str, symbols: list[LegendSymbol]):
    """Replace all symbols in a legend (bulk update after review)."""
    if legend_id not in legend_store:
        raise HTTPException(404, "Legend not found")

    legend = legend_store[legend_id]
    legend.symbols = symbols
    legend.total_symbols = len(symbols)
    legend.systems = list({s.category for s in symbols if s.category})

    logger.info(f"Legend {legend_id}: bulk replaced with {len(symbols)} symbols")
    return {"status": "ok", "total_symbols": len(symbols)}


@app.post("/api/upload", response_model=ParseResponse)
async def upload_drawing(file: UploadFile, legend_id: str | None = None):
    logger.info("=== DRAWING UPLOAD START ===")
    logger.info(f"Filename: {file.filename}, legend_id: {legend_id!r}")

    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".dxf", ".dwg", ".pdf"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Supported: .dxf, .dwg, .pdf")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"File too large ({size_mb:.1f}MB). Max is {MAX_FILE_SIZE_MB}MB.")

    drawing_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{drawing_id}{ext}"
    save_path.write_bytes(contents)

    # Resolve legend if provided
    legend = legend_store.get(legend_id) if legend_id else None
    if legend_id:
        if legend:
            logger.info(
                f"Legend resolved: {legend.filename} ({legend.total_symbols} symbols, "
                f"systems: {legend.systems})"
            )
        else:
            logger.warning(
                f"legend_id={legend_id!r} was provided but NOT FOUND in legend_store! "
                f"Available legend IDs: {list(legend_store.keys())}"
            )
    else:
        logger.info("No legend_id provided — using dictionary fast-path")

    # PDF drawings: use AI vision instead of DXF parsing
    if ext == ".pdf":
        try:
            parse_result = await parse_drawing_pdf_with_vision(
                pdf_data=contents,
                media_type="application/pdf",
                filename=file.filename,
                legend=legend,
            )
            # Override the drawing_id to match what we generated
            parse_result.drawing_id = drawing_id
        except Exception as e:
            logger.error(f"PDF vision analysis failed: {e}")
            raise HTTPException(500, f"Failed to analyze PDF drawing: {str(e)}")

        # Store result and return (skip DXF-specific processing)
        drawings_store[drawing_id] = parse_result
        if legend_id:
            drawing_legend_map[drawing_id] = legend_id
        logger.info(
            f"PDF drawing stored: id={drawing_id}, "
            f"{parse_result.total_symbols} devices, {len(parse_result.symbols)} types"
        )
        return parse_result

    try:
        if ext == ".dxf":
            parse_result = parse_dxf_file(str(save_path), use_fast_path=not legend)
        elif ext == ".dwg":
            parse_result = parse_dwg_file(str(save_path), use_fast_path=not legend)
        else:
            raise HTTPException(400, f"Unsupported file type: {ext}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to parse drawing: {str(e)}")

    if legend:
        parse_result.analysis.append({
            "type": "success",
            "message": f"Using uploaded legend \"{legend.filename}\" ({legend.total_symbols} symbols) as classification source",
        })
        # === DEBUG: Show all legend symbols extracted by vision AI ===
        parse_result.analysis.append({
            "type": "section",
            "message": f"LEGEND EXTRACTION — {legend.total_symbols} symbols from \"{legend.filename}\"",
        })
        # Group by category for readability
        by_category: dict[str, list] = {}
        for ls in legend.symbols:
            by_category.setdefault(ls.category, []).append(ls)
        for cat, symbols_in_cat in sorted(by_category.items()):
            parse_result.analysis.append({
                "type": "detail",
                "message": f"[{cat}] ({len(symbols_in_cat)} symbols):",
            })
            for ls in symbols_in_cat:
                parts = [f'code="{ls.code}"', f'name="{ls.name}"']
                if ls.shape:
                    parts.append(f'shape="{ls.shape}"')
                parts.append(f'shape_code={ls.shape_code}')
                if ls.filled:
                    parts.append("FILLED")
                if ls.svg_icon:
                    parts.append("has_svg=yes")
                parse_result.analysis.append({
                    "type": "detail",
                    "message": f"  • {', '.join(parts)}",
                })

    # === FILTER NON-DEVICE BLOCKS ===
    # Remove blocks that are clearly not fire alarm devices before classification.
    # These cause false positives when their block names contain segments that
    # fuzzy-match legend codes (e.g., "Grid" blocks matching "LAN", XREF blocks
    # matching "IP").
    #
    # IMPORTANT: When a legend is provided, SKIP this filter entirely.
    # The legend is the authoritative source of truth — legend matching strategies
    # and legend-constrained AI classification are sufficient to distinguish devices
    # from non-devices. Filtering by block name patterns here would drop valid
    # fire alarm blocks that happen to have prefixes like "AR-" (common in many
    # CAD naming conventions for alarm/fire blocks).
    filtered_candidates = []
    filtered_out_count = 0

    if legend:
        # Legend mode: trust the legend + AI pipeline, don't pre-filter by name
        filtered_candidates = list(parse_result.ai_candidate_blocks)
        parse_result.analysis.append({
            "type": "info",
            "message": (
                "Legend provided — skipping non-device name filter "
                "(legend matching + AI will classify all blocks)"
            ),
        })
    else:
        for block in parse_result.ai_candidate_blocks:
            # Check against non-device patterns (module-level _NON_DEVICE_BLOCK_PATTERNS)
            is_non_device = any(p.search(block.block_name) for p in _NON_DEVICE_BLOCK_PATTERNS)
            if is_non_device:
                filtered_out_count += block.count
                continue
            filtered_candidates.append(block)

        if filtered_out_count > 0:
            parse_result.analysis.append({
                "type": "detail",
                "message": (
                    f"Filtered out {filtered_out_count} non-device entities "
                    f"(architectural, structural, furniture, plumbing blocks)"
                ),
            })

    # === DIRECT LEGEND CODE MATCHING ===
    # Before AI classification, try to match blocks directly against legend codes
    # using multiple strategies (attribute values, attdef defaults, block def text,
    # block name segments). Much more accurate than AI guessing from names alone.
    all_candidates = filtered_candidates
    blocks_to_classify = []  # Blocks that still need AI classification
    direct_matched_count = 0

    if legend:
        # Build lookup: legend code (uppercase) → LegendSymbol
        legend_code_lookup: dict[str, "LegendSymbol"] = {}
        for ls in legend.symbols:
            if ls.code:
                legend_code_lookup[ls.code.upper().strip()] = ls

        # Show available legend codes for debugging
        parse_result.analysis.append({
            "type": "section",
            "message": f"DIRECT LEGEND CODE MATCHING — {len(legend_code_lookup)} legend codes available",
        })
        # Show all legend codes grouped by category
        codes_by_cat: dict[str, list[str]] = {}
        for ls in legend.symbols:
            if ls.code:
                codes_by_cat.setdefault(ls.category, []).append(ls.code)
        for cat, codes in sorted(codes_by_cat.items()):
            parse_result.analysis.append({
                "type": "detail",
                "message": f'  [{cat}] codes: {", ".join(codes)}',
            })

        logger.info(
            f"Direct legend matching: {len(legend_code_lookup)} legend codes available: "
            f"{', '.join(sorted(legend_code_lookup.keys())[:30])}"
        )

        # Pre-compute legend names sorted by length (longest first) for Strategy 6.
        # Longest-first ensures the most specific match wins (e.g., "Above False Ceiling
        # Photoelectric Smoke Detector" matches before "Smoke Detector").
        # Filter to 2+ word names to avoid false positives on single-word names.
        _NOISE_WORDS = {"FOR", "THE", "AND", "WITH", "TO", "OF", "IN", "AT", "ON", "A", "AN"}
        legend_names_by_length: list["LegendSymbol"] = []
        # Separate dict for pre-computed match words (avoids monkey-patching Pydantic model)
        legend_match_words: dict[str, list[str]] = {}  # keyed by "code:name" to handle duplicates
        for ls in sorted(legend.symbols, key=lambda s: -len(s.name)):
            name_upper = ls.name.upper().strip()
            if len(name_upper.split()) < 2:
                continue
            # Pre-compute significant words for word-overlap matching (Strategy 6c).
            # Keep ALL words including parenthesized qualifiers like (Weatherproof),
            # (Indoor), (Ceiling Mounted), etc. — these become REQUIRED match words,
            # so "Fire Alarm Siren (Weatherproof)" only matches blocks that actually
            # contain "WEATHERPROOF". Split on parens as delimiters, not strip them.
            words = [
                w for w in re.split(r'[-_\s.,/()]+', name_upper)
                if len(w) >= 2 and w not in _NOISE_WORDS
            ]
            key = f"{ls.code}:{ls.name}"
            legend_match_words[key] = words
            legend_names_by_length.append(ls)

        # Segment exclusion list for Strategies 5 and 8: common drawing title words
        # and Revit naming prefixes that should never be matched as device codes.
        _SEGMENT_EXCLUSIONS = {
            # Drawing title words (from "FIRE ALARM _ VOICE EVACUATION SYSTEMS_ GROUND FLOOR PLAN OVERALL")
            "FIRE", "ALARM", "VOICE", "EVACUATION", "SYSTEMS", "GROUND", "FLOOR",
            "PLAN", "OVERALL", "LEVEL", "LAYOUT", "SHEET", "DRAWING", "VIEW",
            "FIRST", "SECOND", "THIRD", "BASEMENT", "ROOF", "MEZZANINE",
            # Revit structural/architectural prefixes (only exclude unambiguous ones;
            # AR/ST/EL/IT can be valid fire alarm legend codes in some projects)
            "IP", "ID", "ME",
            # Common non-device words
            "RVT", "DWG", "DXF", "CAD", "REV", "MODEL", "SPACE",
            "GRID", "HEAD", "CIRCLED", "GRIDLINES",
            # Architectural elements
            "WALL", "DOOR", "WINDOW", "COLUMN", "BEAM", "SLAB",
        }

        # Track per-label colors for direct matches
        direct_label_color_map: dict[str, str] = {}
        direct_color_index = 0

        for block in all_candidates:
            matched_legend_sym = None
            match_source = ""
            checked_values: list[str] = []  # Track what we checked for debug

            # Strategy 1: Check sub-group attribute value against legend codes
            if block.sub_group_value:
                val_upper = block.sub_group_value.upper().strip()
                checked_values.append(f"sub_group({block.sub_group_tag})={val_upper}")
                if val_upper in legend_code_lookup:
                    matched_legend_sym = legend_code_lookup[val_upper]
                    match_source = f"attrib {block.sub_group_tag}={block.sub_group_value}"

            # Strategy 2: Check all per-instance attrib VALUES against legend codes
            if not matched_legend_sym and block.attribs:
                for tag, value in block.attribs.items():
                    val_upper = value.upper().strip()
                    checked_values.append(f"attrib({tag})={val_upper}")
                    if val_upper in legend_code_lookup:
                        matched_legend_sym = legend_code_lookup[val_upper]
                        match_source = f"attrib {tag}={value}"
                        break

            # Strategy 3: Check block definition ATTDEF default values
            if not matched_legend_sym and block.attdef_tags:
                for tag, default_val in block.attdef_tags.items():
                    val_upper = default_val.upper().strip()
                    checked_values.append(f"attdef({tag})={val_upper}")
                    if val_upper in legend_code_lookup:
                        matched_legend_sym = legend_code_lookup[val_upper]
                        match_source = f"attdef {tag}={default_val}"
                        break

            # Strategy 4: Check block definition's internal TEXT entities
            if not matched_legend_sym and block.texts_inside:
                for text in block.texts_inside:
                    text_upper = text.upper().strip()
                    checked_values.append(f"text_inside={text_upper}")
                    if text_upper in legend_code_lookup:
                        matched_legend_sym = legend_code_lookup[text_upper]
                        match_source = f"text_inside={text}"
                        break

            # Strategy 5: Parse block name segments and match against legend codes
            # Block names like "IT-DVC-FAM-Fire Modules-111" → segments: IT, DVC, FAM, Fire, Modules, 111
            # Only match codes that are 2+ chars to avoid false positives with single-char codes.
            # Exclude common drawing title words and Revit naming prefixes (see _SEGMENT_EXCLUSIONS above).
            if not matched_legend_sym:
                segments = re.split(r'[-_\s.]+', block.block_name)
                for segment in segments:
                    seg_upper = segment.upper().strip()
                    if len(seg_upper) < 2 or seg_upper in _SEGMENT_EXCLUSIONS:
                        continue
                    if seg_upper in legend_code_lookup:
                        checked_values.append(f"name_segment={seg_upper} ✓")
                        matched_legend_sym = legend_code_lookup[seg_upper]
                        match_source = f"block_name_segment={segment}"
                        break
                    else:
                        checked_values.append(f"name_segment={seg_upper}")

            # Strategy 6: Match legend NAMES against block name description text
            # Handles Revit-style blocks like "IT-DVC-DET-Detectors - SMOKE DETECTOR-3159778-..."
            # where the legend code ("S") doesn't appear but the device name ("Smoke Detector") does.
            #
            # Three sub-strategies, tried in order:
            #   6a. Full legend name substring match (longest legend name wins for specificity)
            #   6b. Block description extracted from Revit naming pattern, matched bidirectionally
            #   6c. Word-overlap: ALL significant words from a legend name appear in the block name
            if not matched_legend_sym:
                block_name_upper = block.block_name.upper()

                # 6a: Check if any legend name (2+ words) appears as a substring in the block name.
                # Pre-sorted longest-first so the first hit is the most specific match.
                for ls in legend_names_by_length:
                    legend_name_upper = ls.name.upper().strip()
                    if legend_name_upper in block_name_upper:
                        matched_legend_sym = ls
                        match_source = f"name_substring=\"{ls.name}\""
                        checked_values.append(f"name_substr={legend_name_upper} ✓")
                        break
                else:
                    checked_values.append("name_substr=none")

                # 6b: Extract the device description from Revit-style block names and match
                # bidirectionally against legend names.
                # "IT-DVC-DET-Detectors - SMOKE DETECTOR-3159778-..." → "SMOKE DETECTOR"
                # "IT-LGT-ALR-Siren With Strobe - ALARM SIREN INDOOR-..." → "ALARM SIREN INDOOR"
                if not matched_legend_sym:
                    # Try multiple patterns to extract the descriptive portion:
                    # Pattern 1: "prefix - DESCRIPTION-number..." (Revit standard)
                    # Pattern 2: "prefix - DESCRIPTION-Vnumber..." (Revit variant suffix)
                    desc_match = re.search(
                        r' - ([A-Z][A-Z /_()\d]+?)(?:-\d{4,}|-V\d)',
                        block_name_upper,
                    )
                    if desc_match:
                        block_desc = desc_match.group(1).strip()
                        checked_values.append(f"desc_phrase={block_desc}")
                        for ls in legend_names_by_length:
                            ln = ls.name.upper().strip()
                            # Bidirectional: legend name in desc, or desc in legend name
                            if ln in block_desc or block_desc in ln:
                                matched_legend_sym = ls
                                match_source = f"desc_match=\"{ls.name}\" (desc=\"{block_desc}\")"
                                break

                # 6c: Word-overlap — check if ALL significant words from a legend name
                # appear somewhere in the block name. This catches cases like:
                #   block "...SIGNAL CONTROL MODULE-3768932-..." matches legend "Signal Control Module"
                #   even though the full legend name "Signal Control Module (Weatherproof)" doesn't
                #   appear as a substring (because of the "(Weatherproof)" suffix).
                #
                # When multiple legend entries match, prefer the MOST SPECIFIC one —
                # i.e., the entry with the most required words. This works because
                # qualifier words like WEATHERPROOF, INDOOR, CEILING are kept in the
                # word list (not stripped), so they naturally require the block name
                # to contain them. More matching words = tighter fit.
                if not matched_legend_sym:
                    best_word_match: LegendSymbol | None = None
                    best_word_count = 0
                    best_word_match_words: list[str] = []
                    for ls in legend_names_by_length:
                        key = f"{ls.code}:{ls.name}"
                        legend_words = legend_match_words.get(key, [])
                        if len(legend_words) < 2:
                            continue
                        if all(w in block_name_upper for w in legend_words):
                            if len(legend_words) > best_word_count:
                                best_word_match = ls
                                best_word_count = len(legend_words)
                                best_word_match_words = legend_words
                    if best_word_match:
                        matched_legend_sym = best_word_match
                        match_source = f"word_overlap=\"{best_word_match.name}\" (words: {best_word_match_words})"
                        checked_values.append(f"word_overlap={best_word_match.name} ✓")

            # Strategy 7: Nearby text labels — match device codes placed as TEXT
            # near each symbol on the drawing. This is the primary way single-char
            # legend codes ("S", "H") get matched: they appear as standalone TEXT
            # entities placed next to the device symbol on the floor plan.
            # Unlike Strategy 5 (block name segments), single-char codes ARE allowed
            # here because nearby text labels are high-confidence — they're the same
            # codes shown in the project legend.
            if not matched_legend_sym and block.nearby_labels:
                for nl in block.nearby_labels:
                    nl_upper = nl.upper().strip()
                    checked_values.append(f"nearby_label={nl_upper}")
                    if nl_upper in legend_code_lookup:
                        matched_legend_sym = legend_code_lookup[nl_upper]
                        match_source = f"nearby_text_label={nl}"
                        checked_values.append(f"nearby_label={nl_upper} ✓")
                        break
                    # Also try fuzzy match on nearby labels
                    fuzzy_sym, fuzzy_desc = _fuzzy_legend_lookup(nl_upper, legend_code_lookup)
                    if fuzzy_sym:
                        matched_legend_sym = fuzzy_sym
                        match_source = f"nearby_text_fuzzy={fuzzy_desc}"
                        checked_values.append(f"nearby_fuzzy={nl_upper} ✓")
                        break

            # Strategy 8: Fuzzy code matching — separator normalization and
            # Levenshtein distance for attrib values and block name segments
            # that were close-but-not-exact matches in Strategies 1-5.
            if not matched_legend_sym:
                # Try fuzzy on sub_group_value
                if block.sub_group_value:
                    fuzzy_sym, fuzzy_desc = _fuzzy_legend_lookup(
                        block.sub_group_value, legend_code_lookup
                    )
                    if fuzzy_sym:
                        matched_legend_sym = fuzzy_sym
                        match_source = f"fuzzy_subgroup={fuzzy_desc}"
                        checked_values.append(f"fuzzy_subgroup ✓")

                # Try fuzzy on attrib values
                if not matched_legend_sym and block.attribs:
                    for tag, value in block.attribs.items():
                        if tag == "_NEARBY_LABEL":
                            continue  # Already tried in Strategy 7
                        fuzzy_sym, fuzzy_desc = _fuzzy_legend_lookup(
                            value, legend_code_lookup
                        )
                        if fuzzy_sym:
                            matched_legend_sym = fuzzy_sym
                            match_source = f"fuzzy_attrib({tag})={fuzzy_desc}"
                            checked_values.append(f"fuzzy_attrib({tag}) ✓")
                            break

                # Try fuzzy on block name segments (reuse same exclusion list)
                if not matched_legend_sym:
                    segments = re.split(r'[-_\s.]+', block.block_name)
                    for segment in segments:
                        seg_upper = segment.upper().strip()
                        if len(seg_upper) < 2 or seg_upper in _SEGMENT_EXCLUSIONS:
                            continue
                        fuzzy_sym, fuzzy_desc = _fuzzy_legend_lookup(
                            seg_upper, legend_code_lookup
                        )
                        if fuzzy_sym:
                            matched_legend_sym = fuzzy_sym
                            match_source = f"fuzzy_segment={fuzzy_desc}"
                            checked_values.append(f"fuzzy_segment ✓")
                            break

            if matched_legend_sym:
                # DIRECT MATCH — no AI needed
                direct_matched_count += 1
                label = matched_legend_sym.name

                if label not in direct_label_color_map:
                    direct_label_color_map[label] = get_symbol_palette_color(direct_color_index)
                    direct_color_index += 1

                parse_result.analysis.append({
                    "type": "detail",
                    "message": (
                        f'  ✓ "{block.block_name}"'
                        f'{f" [{block.sub_group_value}]" if block.sub_group_value else ""}'
                        f' (×{block.count}) → "{label}" via {match_source}'
                    ),
                })
                logger.info(
                    f"  DIRECT MATCH: \"{block.block_name}\" → \"{label}\" via {match_source}"
                )

                parse_result.symbols.append(SymbolInfo(
                    block_name=block.block_name,
                    label=label,
                    count=block.count,
                    locations=block.locations,
                    color=direct_label_color_map[label],
                    confidence="high",
                    source="legend",
                    shape_code=matched_legend_sym.shape_code or "circle",
                    category=matched_legend_sym.category,
                    legend_code=matched_legend_sym.code,
                    legend_shape=matched_legend_sym.shape,
                    svg_icon=matched_legend_sym.svg_icon,
                ))
                parse_result.audit.append(AuditEntry(
                    block_name=block.block_name,
                    label=label,
                    count=block.count,
                    method="legend_direct",
                    confidence="high",
                    matched_term=match_source,
                    layers=block.layers,
                ))
            else:
                # No direct match — goes to AI
                blocks_to_classify.append(block)
                # Debug: show WHY this block didn't match
                parse_result.analysis.append({
                    "type": "detail",
                    "message": (
                        f'  ✗ "{block.block_name}" (×{block.count}) — no match. '
                        f'Checked: [{", ".join(checked_values[:8])}]'
                        f'{"..." if len(checked_values) > 8 else ""}'
                    ),
                })

        if direct_matched_count > 0:
            total_direct_devices = sum(
                b.count for b in all_candidates if b not in blocks_to_classify
            )
            parse_result.analysis.append({
                "type": "success",
                "message": (
                    f"Direct legend code matching: {direct_matched_count} block types matched "
                    f"({total_direct_devices} devices), "
                    f"{len(blocks_to_classify)} blocks remaining for AI"
                ),
            })
        else:
            parse_result.analysis.append({
                "type": "info",
                "message": (
                    "Direct legend code matching: no matches found. "
                    "Blocks had no attribs/attdefs/texts/name-segments matching legend codes. "
                    "All blocks sent to AI."
                ),
            })
        logger.info(
            f"Direct legend matching result: {direct_matched_count} matched, "
            f"{len(blocks_to_classify)} remaining for AI"
        )
    else:
        blocks_to_classify = list(all_candidates)

    logger.info(
        f"Blocks to classify: {len(blocks_to_classify)}, "
        f"fast_path_symbols: {len(parse_result.fast_path_symbols)}, "
        f"mode: {'legend+AI' if legend else 'dictionary+AI'}"
    )

    # === DEBUG: Show all DXF blocks being sent to AI ===
    if blocks_to_classify:
        parse_result.analysis.append({
            "type": "section",
            "message": f"BLOCK INVENTORY — {len(blocks_to_classify)} DXF blocks sent to AI",
        })
        for blk in sorted(blocks_to_classify, key=lambda b: -b.count):
            parts = [f'count={blk.count}']
            if blk.sub_group_value:
                parts.append(f'{blk.sub_group_tag}={blk.sub_group_value}')
            if blk.layers:
                parts.append(f'layers=[{", ".join(blk.layers[:3])}]')
            if blk.texts_inside:
                parts.append(f'texts={blk.texts_inside[:3]}')
            if blk.attribs:
                parts.append(f'attrs={dict(list(blk.attribs.items())[:3])}')
            if blk.description:
                parts.append(f'desc="{blk.description[:50]}"')
            parse_result.analysis.append({
                "type": "detail",
                "message": f'  "{blk.block_name}" — {", ".join(parts)}',
            })

    if blocks_to_classify:
        try:
            fast_path_labels = {
                s.block_name: s.label for s in parse_result.fast_path_symbols
            }

            logger.info(
                f"Sending {len(blocks_to_classify)} blocks to AI classification"
                f"{f' with legend ({legend.total_symbols} symbols)' if legend else ''}..."
            )

            ai_labels = await classify_blocks_with_ai(
                ai_candidate_blocks=blocks_to_classify,
                filename=file.filename,
                all_block_names=parse_result.all_block_names,
                all_layer_names=parse_result.all_layer_names,
                fire_layers=parse_result.fire_layers,
                legend_texts=parse_result.legend_texts,
                fast_path_labels=fast_path_labels,
                legend=legend,
            )

            logger.info(f"AI classification returned {len(ai_labels)} identified devices")
            if ai_labels:
                for k, v in ai_labels.items():
                    logger.debug(f"  AI: {k!r} → {v!r}")

            # === DEBUG: Show full AI classification results ===
            parse_result.analysis.append({
                "type": "section",
                "message": f"AI CLASSIFICATION RESULTS — {len(ai_labels)} identified, "
                f"{len(blocks_to_classify) - len(ai_labels)} skipped (null)",
            })
            # Show identified blocks
            if ai_labels:
                for block_name, label in sorted(ai_labels.items()):
                    # Find the block's count
                    blk_count = next(
                        (b.count for b in blocks_to_classify if b.block_name == block_name), "?"
                    )
                    parse_result.analysis.append({
                        "type": "detail",
                        "message": f'  ✓ "{block_name}" (×{blk_count}) → "{label}"',
                    })
            # Show skipped blocks (null) — these are the ones AI rejected
            skipped_blocks = [
                b for b in blocks_to_classify if b.block_name not in ai_labels
            ]
            if skipped_blocks:
                parse_result.analysis.append({
                    "type": "detail",
                    "message": f"  — {len(skipped_blocks)} blocks classified as null (not devices):",
                })
                for blk in sorted(skipped_blocks, key=lambda b: -b.count)[:30]:
                    parse_result.analysis.append({
                        "type": "detail",
                        "message": f'  ✗ "{blk.block_name}" (×{blk.count}) → null',
                    })
                if len(skipped_blocks) > 30:
                    parse_result.analysis.append({
                        "type": "detail",
                        "message": f"  ... and {len(skipped_blocks) - 30} more null blocks",
                    })

            if ai_labels:
                source_label = "legend + AI" if legend else "AI"
                parse_result.analysis.append({
                    "type": "success",
                    "message": f"{source_label} classified {len(ai_labels)} block types as devices",
                })

                # Build legend lookup for category/shape/color when legend is available
                legend_lookup: dict[str, "LegendSymbol"] = {}
                if legend:
                    for ls in legend.symbols:
                        legend_lookup[ls.name.upper()] = ls

                # === DEBUG: Legend lookup section ===
                if legend:
                    parse_result.analysis.append({
                        "type": "section",
                        "message": "LEGEND LOOKUP — matching AI labels to legend symbols",
                    })

                # Track unique labels for per-symbol color assignment
                label_color_map: dict[str, str] = {}
                color_index = 0

                for block in blocks_to_classify:
                    # Build the lookup key matching what we sent to the AI.
                    # Sub-grouped blocks use composite keys: "block_name|TAG=VALUE"
                    if block.sub_group_value:
                        ai_key = f"{block.block_name}|{block.sub_group_tag}={block.sub_group_value}"
                    else:
                        ai_key = block.block_name
                    if ai_key in ai_labels:
                        label = ai_labels[ai_key]

                        # Look up legend symbol for category, shape, code, and color
                        matched_legend = legend_lookup.get(label.upper())
                        match_method = "exact" if matched_legend else None
                        if not matched_legend:
                            # Fuzzy matching — prefer the closest match by:
                            # 1. The AI label is a substring of a legend name, or vice versa
                            # 2. Among all matches, prefer the SHORTEST legend name
                            #    (avoids "Smoke Detector" matching "Above False Ceiling
                            #     Photoelectric Smoke Detector" instead of "Smoke Detector")
                            label_upper = label.upper()
                            best_fuzzy = None
                            best_fuzzy_len = float('inf')
                            for lname, ls in legend_lookup.items():
                                if lname == label_upper:
                                    best_fuzzy = ls
                                    best_fuzzy_len = 0
                                    break
                                if label_upper in lname or lname in label_upper:
                                    if len(lname) < best_fuzzy_len:
                                        best_fuzzy = ls
                                        best_fuzzy_len = len(lname)
                            if best_fuzzy:
                                matched_legend = best_fuzzy
                                match_method = "fuzzy"

                        # Source/confidence based on whether the label actually
                        # matches a real legend entry — not just whether a legend
                        # was uploaded. This prevents hallucinated legend entries
                        # from getting the "LEGEND" badge.
                        if legend and matched_legend:
                            confidence = "high"
                            source = "legend"
                        elif legend:
                            # Legend uploaded but AI label doesn't match any entry
                            confidence = "medium"
                            source = "ai"
                        else:
                            confidence = "medium"
                            source = "ai"

                        # === DEBUG: Log each legend lookup result ===
                        if legend:
                            if matched_legend:
                                parse_result.analysis.append({
                                    "type": "detail",
                                    "message": (
                                        f'  ✓ "{label}" → legend [{match_method}]: '
                                        f'code="{matched_legend.code}", '
                                        f'cat="{matched_legend.category}", '
                                        f'shape={matched_legend.shape_code}'
                                    ),
                                })
                            else:
                                parse_result.analysis.append({
                                    "type": "detail",
                                    "message": (
                                        f'  ✗ "{label}" → NO LEGEND MATCH '
                                        f'(AI returned a label not in the legend — source set to "ai")'
                                    ),
                                })

                        # Assign a unique color per label (device type)
                        if label not in label_color_map:
                            label_color_map[label] = get_symbol_palette_color(color_index)
                            color_index += 1

                        color = label_color_map[label]
                        legend_code = ""
                        shape_code = "circle"
                        category = ""
                        legend_shape = ""
                        svg_icon = ""

                        if matched_legend:
                            legend_code = matched_legend.code
                            shape_code = matched_legend.shape_code or "circle"
                            category = matched_legend.category
                            legend_shape = matched_legend.shape
                            svg_icon = matched_legend.svg_icon

                        parse_result.symbols.append(
                            SymbolInfo(
                                block_name=block.block_name,
                                label=label,
                                count=block.count,
                                locations=block.locations,
                                color=color,
                                confidence=confidence,
                                source=source,
                                shape_code=shape_code,
                                category=category,
                                legend_code=legend_code,
                                legend_shape=legend_shape,
                                svg_icon=svg_icon,
                            )
                        )
                        parse_result.audit.append(AuditEntry(
                            block_name=block.block_name,
                            label=label,
                            count=block.count,
                            method="legend_ai" if (legend and matched_legend) else "ai",
                            confidence=confidence,
                            layers=block.layers,
                        ))
            else:
                n = len(blocks_to_classify)
                parse_result.analysis.append({
                    "type": "info",
                    "message": f"AI analyzed {n} blocks — none identified as devices",
                })
        except Exception as e:
            logger.error(f"AI classification FAILED: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())
            parse_result.analysis.append({
                "type": "warning",
                "message": f"AI classification failed: {type(e).__name__}: {str(e)[:200]}",
            })
    else:
        logger.info("No blocks to classify — all handled by fast-path")

    # Legend coverage analysis — tell the user which systems were found vs missing
    if legend:
        detected_labels = {s.label.upper() for s in parse_result.symbols}
        matched_legend_symbols = []
        unmatched_legend_symbols = []
        for ls in legend.symbols:
            # Check if any detected label contains the legend symbol name
            name_upper = ls.name.upper()
            if any(name_upper in dl or dl in name_upper for dl in detected_labels):
                matched_legend_symbols.append(ls)
            else:
                unmatched_legend_symbols.append(ls)

        # Report by system category
        detected_categories = set()
        for s in parse_result.symbols:
            # Find which legend category this symbol belongs to
            for ls in legend.symbols:
                if ls.name.upper() in s.label.upper() or s.label.upper() in ls.name.upper():
                    detected_categories.add(ls.category)
                    break

        all_categories = set(ls.category for ls in legend.symbols)
        missing_categories = all_categories - detected_categories

        parse_result.analysis.append({
            "type": "section",
            "message": f"LEGEND COVERAGE — {len(matched_legend_symbols)}/{len(legend.symbols)} symbols matched",
        })
        parse_result.analysis.append({
            "type": "info",
            "message": (
                f"Legend coverage: {len(matched_legend_symbols)}/{len(legend.symbols)} legend symbols "
                f"found in this drawing. Systems detected: {', '.join(sorted(detected_categories)) or 'none'}"
            ),
        })

        # === DEBUG: Show matched legend symbols ===
        if matched_legend_symbols:
            parse_result.analysis.append({
                "type": "detail",
                "message": f"  Matched ({len(matched_legend_symbols)}):",
            })
            for ls in matched_legend_symbols:
                parse_result.analysis.append({
                    "type": "detail",
                    "message": f'    ✓ [{ls.category}] "{ls.code}" — {ls.name}',
                })

        # === DEBUG: Show unmatched legend symbols (this is the key diagnostic!) ===
        if unmatched_legend_symbols:
            parse_result.analysis.append({
                "type": "detail",
                "message": f"  NOT found in drawing ({len(unmatched_legend_symbols)}):",
            })
            for ls in unmatched_legend_symbols:
                parse_result.analysis.append({
                    "type": "detail",
                    "message": f'    ✗ [{ls.category}] "{ls.code}" — {ls.name}',
                })

        if missing_categories:
            parse_result.analysis.append({
                "type": "info",
                "message": (
                    f"Systems NOT found in this drawing: {', '.join(sorted(missing_categories))}. "
                    "These may be on separate drawing sheets."
                ),
            })

    # Consolidate symbols by label — merge different block names that map to
    # the same device type (e.g., 4 different "Control Module" block variants
    # become one "Control Module" row with combined counts and locations).
    # Contractors need to see "Control Module: 35" not 4 separate rows.
    label_groups: dict[str, list[SymbolInfo]] = {}
    for sym in parse_result.symbols:
        label_groups.setdefault(sym.label, []).append(sym)

    # === DEBUG: Consolidation ===
    multi_variant_groups = {k: v for k, v in label_groups.items() if len(v) > 1}
    if multi_variant_groups:
        parse_result.analysis.append({
            "type": "section",
            "message": f"CONSOLIDATION — merging {len(multi_variant_groups)} multi-variant device types",
        })
        for label, group in multi_variant_groups.items():
            variants = ", ".join(f'"{s.block_name}" (×{s.count})' for s in group)
            total = sum(s.count for s in group)
            parse_result.analysis.append({
                "type": "detail",
                "message": f'  "{label}" (total ×{total}): {variants}',
            })

    consolidated_symbols = []
    for label, group in label_groups.items():
        if len(group) == 1:
            consolidated_symbols.append(group[0])
        else:
            total_count = sum(s.count for s in group)
            all_locations = []
            for s in group:
                all_locations.extend(s.locations)
            sorted_group = sorted(group, key=lambda s: -s.count)
            block_names = [s.block_name for s in sorted_group]
            if len(block_names) <= 3:
                combined_name = " + ".join(block_names)
            else:
                combined_name = f"{block_names[0]} (+{len(block_names)-1} variants)"
            # Use highest confidence level in group
            confidence_rank = {"high": 3, "medium": 2, "low": 1}
            best_confidence = max(group, key=lambda s: confidence_rank.get(s.confidence, 0)).confidence
            # If any source is dictionary, mark as dictionary; legend takes priority over ai
            sources = {s.source for s in group}
            if "dictionary" in sources:
                best_source = "dictionary"
            elif "legend" in sources:
                best_source = "legend"
            elif "ai" in sources:
                best_source = "ai"
            else:
                best_source = "manual"
            consolidated_symbols.append(SymbolInfo(
                block_name=combined_name,
                label=label,
                count=total_count,
                locations=all_locations,
                color=group[0].color,
                confidence=best_confidence,
                source=best_source,
                block_variants=block_names,
                shape_code=group[0].shape_code,
                category=group[0].category,
                legend_code=group[0].legend_code,
                legend_shape=group[0].legend_shape,
                svg_icon=group[0].svg_icon,
            ))

    # Sort by count descending
    consolidated_symbols.sort(key=lambda s: -s.count)

    # Convert analysis dicts to AnalysisStep models
    analysis_steps = [
        AnalysisStep(**step) for step in parse_result.analysis
    ]

    # Build audit entries
    audit_entries = [
        AuditEntry(**a) if isinstance(a, dict) else a
        for a in parse_result.audit
    ]

    result = ParseResponse(
        drawing_id=drawing_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        symbols=consolidated_symbols,
        total_symbols=sum(s.count for s in consolidated_symbols),
        analysis=analysis_steps,
        audit=audit_entries,
        xref_warnings=parse_result.xref_warnings,
        legend_texts=parse_result.legend_texts,
    )
    drawings_store[drawing_id] = result

    # Store the effective DXF path for preview generation.
    # For DWG files, this is the converted DXF (not the original .dwg).
    # For DXF files, this is the original file.
    effective_path = parse_result.dxf_path or str(save_path)
    file_paths_store[drawing_id] = effective_path

    # Link drawing to legend if one was used
    if legend_id and legend_id in legend_store:
        drawing_legend_map[drawing_id] = legend_id

    return result


@app.get("/api/drawings/{drawing_id}", response_model=ParseResponse)
def get_drawing(drawing_id: str):
    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")
    return drawings_store[drawing_id]


@app.get("/api/drawings/{drawing_id}/preview", response_model=PreviewResponse)
def get_drawing_preview(drawing_id: str):
    """Generate or return cached SVG preview of the drawing."""
    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")
    if drawing_id not in file_paths_store:
        raise HTTPException(404, "Drawing file not available for preview")

    # Return cached preview if available
    if drawing_id in preview_cache:
        return PreviewResponse(**preview_cache[drawing_id])

    drawing = drawings_store[drawing_id]
    filepath = file_paths_store[drawing_id]

    import logging
    logger = logging.getLogger(__name__)
    try:
        preview_data = generate_drawing_preview(filepath, drawing.symbols)
    except Exception as e:
        logger.error(f"Preview generation failed for {drawing_id}: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to generate preview: {str(e)}")

    preview_cache[drawing_id] = preview_data
    return PreviewResponse(**preview_data)


# ── Project Endpoints (Phase 4: Multi-Sheet & Batch Processing) ──


@app.post("/api/projects", response_model=ProjectData)
async def create_project(name: str = "Untitled Project", legend_id: str | None = None):
    """Create a new project. Optionally attach a confirmed legend."""
    project_id = str(uuid.uuid4())

    # Validate legend if provided
    if legend_id and legend_id not in legend_store:
        raise HTTPException(404, f"Legend {legend_id} not found")

    project = ProjectData(
        project_id=project_id,
        name=name,
        legend_id=legend_id,
        drawing_ids=[],
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    project_store[project_id] = project
    logger.info(f"Created project {project_id}: {name} (legend={legend_id})")
    return project


@app.get("/api/projects")
def list_projects():
    """List all projects with basic info."""
    results = []
    for p in project_store.values():
        results.append({
            "project_id": p.project_id,
            "name": p.name,
            "legend_id": p.legend_id,
            "drawing_count": len(p.drawing_ids),
            "created_at": p.created_at,
        })
    return results


@app.get("/api/projects/{project_id}", response_model=ProjectData)
def get_project(project_id: str):
    """Get project details."""
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")
    return project_store[project_id]


@app.post("/api/projects/{project_id}/upload-drawing", response_model=ParseResponse)
async def project_upload_drawing(project_id: str, file: UploadFile):
    """Upload a drawing to a project. Uses the project's legend for classification.

    Delegates to the main upload endpoint, then links the drawing to the project.
    """
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")

    project = project_store[project_id]

    # Delegate to main upload endpoint (reuses full classification pipeline)
    result = await upload_drawing(file, legend_id=project.legend_id)

    # Link drawing to project
    project.drawing_ids.append(result.drawing_id)
    drawing_project_map[result.drawing_id] = project_id

    logger.info(
        f"Project {project_id}: added drawing {result.drawing_id} ({result.filename}), "
        f"{result.total_symbols} symbols, {len(project.drawing_ids)} sheets total"
    )

    return result


@app.get("/api/projects/{project_id}/summary", response_model=ProjectSummary)
def get_project_summary(project_id: str):
    """Get aggregated symbol counts across all drawings in the project."""
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")

    project = project_store[project_id]

    # Aggregate symbols across all sheets
    merged: dict[str, SymbolInfo] = {}  # label → merged SymbolInfo
    per_sheet: dict[str, list[SymbolInfo]] = {}

    for did in project.drawing_ids:
        drawing = drawings_store.get(did)
        if not drawing:
            continue

        per_sheet[did] = drawing.symbols

        for sym in drawing.symbols:
            key = sym.label.lower().strip()
            if key in merged:
                existing = merged[key]
                merged[key] = SymbolInfo(
                    block_name=existing.block_name,
                    label=existing.label,
                    count=existing.count + sym.count,
                    locations=existing.locations + sym.locations,
                    color=existing.color,
                    confidence=existing.confidence,
                    source=existing.source,
                    block_variants=list(set(existing.block_variants + sym.block_variants + [sym.block_name])),
                    shape_code=existing.shape_code,
                    category=existing.category or sym.category,
                    legend_code=existing.legend_code or sym.legend_code,
                    legend_shape=existing.legend_shape or sym.legend_shape,
                    svg_icon=existing.svg_icon or sym.svg_icon,
                )
            else:
                merged[key] = sym.model_copy()

    all_symbols = sorted(merged.values(), key=lambda s: s.count, reverse=True)
    total = sum(s.count for s in all_symbols)

    drawings_info = []
    for did in project.drawing_ids:
        d = drawings_store.get(did)
        if d:
            drawings_info.append(ProjectDrawingInfo(
                drawing_id=did,
                filename=d.filename,
                file_type=d.file_type,
                total_symbols=d.total_symbols,
                symbol_types=len(d.symbols),
            ))

    return ProjectSummary(
        project_id=project_id,
        project_name=project.name,
        total_drawings=len(project.drawing_ids),
        total_symbols=total,
        total_types=len(all_symbols),
        symbols=all_symbols,
        per_sheet=per_sheet,
        drawings=drawings_info,
    )


@app.post("/api/projects/{project_id}/chat", response_model=ChatResponse)
async def project_chat(project_id: str, request: ProjectChatRequest):
    """Chat with project-wide context — all drawings' symbols injected."""
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")

    project = project_store[project_id]
    if not project.drawing_ids:
        raise HTTPException(400, "No drawings in this project yet. Upload drawings first.")

    # Gather all drawings in the project
    drawings = []
    for did in project.drawing_ids:
        d = drawings_store.get(did)
        if d:
            drawings.append(d)

    legend = legend_store.get(project.legend_id) if project.legend_id else None

    history = None
    if request.history:
        history = [{"role": h.role, "content": h.content} for h in request.history]

    from app.chat import chat_with_project
    response_text = await chat_with_project(
        request.message, drawings, history, legend, request.active_drawing_id
    )
    return ChatResponse(response=response_text)


@app.post("/api/projects/{project_id}/chat/stream")
async def project_chat_stream(project_id: str, request: ProjectChatRequest):
    """Streaming chat with project-wide context via SSE."""
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")

    project = project_store[project_id]
    if not project.drawing_ids:
        raise HTTPException(400, "No drawings in this project yet.")

    drawings = []
    for did in project.drawing_ids:
        d = drawings_store.get(did)
        if d:
            drawings.append(d)

    legend = legend_store.get(project.legend_id) if project.legend_id else None

    history = None
    if request.history:
        history = [{"role": h.role, "content": h.content} for h in request.history]

    from app.chat import chat_with_project_stream

    async def event_generator():
        try:
            async for chunk in chat_with_project_stream(
                request.message, drawings, history, legend, request.active_drawing_id
            ):
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Project streaming chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, name: str | None = None, legend_id: str | None = None):
    """Update project name or legend."""
    if project_id not in project_store:
        raise HTTPException(404, "Project not found")

    project = project_store[project_id]
    if name is not None:
        project.name = name
    if legend_id is not None:
        if legend_id and legend_id not in legend_store:
            raise HTTPException(404, f"Legend {legend_id} not found")
        project.legend_id = legend_id

    return project


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if request.drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found. Please upload a drawing first.")

    drawing = drawings_store[request.drawing_id]

    # Build history from request
    history = None
    if request.history:
        history = [{"role": h.role, "content": h.content} for h in request.history]

    # Pass legend context to chat if available
    legend = None
    legend_id = drawing_legend_map.get(request.drawing_id)
    if legend_id:
        legend = legend_store.get(legend_id)

    response_text = await chat_with_drawing(request.message, drawing, history, legend)
    return ChatResponse(response=response_text)


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint using Server-Sent Events (SSE).

    Streams text chunks as they arrive from the AI model for real-time display.
    Each SSE event has data: {"text": "chunk"} or data: {"done": true}.
    """
    if request.drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found. Please upload a drawing first.")

    drawing = drawings_store[request.drawing_id]

    history = None
    if request.history:
        history = [{"role": h.role, "content": h.content} for h in request.history]

    legend = None
    legend_id = drawing_legend_map.get(request.drawing_id)
    if legend_id:
        legend = legend_store.get(legend_id)

    async def event_generator():
        try:
            async for chunk in chat_with_drawing_stream(
                request.message, drawing, history, legend
            ):
                # SSE format: data: JSON\n\n
                yield f"data: {json.dumps({'text': chunk})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as e:
            logger.error(f"Streaming chat error: {e}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.patch("/api/drawings/{drawing_id}/symbols/{block_name}")
def override_symbol(drawing_id: str, block_name: str, override: SymbolOverride):
    """Manual count override for a symbol. Tracks original count for audit."""
    if override.count < 0:
        raise HTTPException(400, "Count cannot be negative")
    if not override.label or not override.label.strip():
        raise HTTPException(400, "Label cannot be empty")

    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")

    drawing = drawings_store[drawing_id]
    for sym in drawing.symbols:
        if sym.block_name == block_name:
            if sym.original_count is None:
                sym.original_count = sym.count
            sym.count = override.count
            sym.label = override.label
            sym.confidence = "manual"
            sym.source = "manual"
            drawing.total_symbols = sum(s.count for s in drawing.symbols)
            drawings_store[drawing_id] = drawing
            return {"status": "ok", "symbol": sym}

    raise HTTPException(404, f"Symbol '{block_name}' not found")


@app.get("/api/drawings/{drawing_id}/export")
def export_drawing_csv(drawing_id: str):
    """Export symbol data as CSV for device schedule comparison."""
    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")

    drawing = drawings_store[drawing_id]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Label", "Block Name", "Count", "Confidence", "Source", "Original Count"])
    for sym in drawing.symbols:
        writer.writerow([
            sym.label,
            sym.block_name,
            sym.count,
            sym.confidence,
            sym.source,
            sym.original_count if sym.original_count is not None else "",
        ])
    writer.writerow([])
    writer.writerow(["Total Devices", "", drawing.total_symbols, "", "", ""])

    output.seek(0)
    safe_name = drawing.filename.rsplit(".", 1)[0] if "." in drawing.filename else drawing.filename
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_symbols.csv"'},
    )


@app.get("/api/drawings")
def list_drawings():
    return {
        "drawings": [
            {"drawing_id": d.drawing_id, "filename": d.filename, "total_symbols": d.total_symbols}
            for d in drawings_store.values()
        ]
    }


# Serve React frontend — must be after all /api routes
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR / "static"), name="static-files")

    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Serve React app for all non-API routes (SPA catch-all)."""
        file_path = STATIC_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")
