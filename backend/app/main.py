import csv
import io
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse

from app.parser import parse_dxf_file, parse_dwg_file, _get_symbol_color
from app.preview import generate_drawing_preview
from app.chat import chat_with_drawing, classify_blocks_with_ai
from app.legend import parse_legend_file, ALL_LEGEND_EXTENSIONS
from app.matching import match_symbols_to_legend
from app.icon_gen import generate_icons_batch, icons_cache
from app.models import (
    AnalysisStep, AuditEntry, ChatRequest, ChatResponse, LegendParseResponse,
    ParseResponse, PreviewResponse, SymbolInfo, SymbolOverride,
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
# Store parsed legends
legends_store: dict[str, LegendParseResponse] = {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload", response_model=ParseResponse)
async def upload_drawing(file: UploadFile):
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".dxf", ".dwg"):
        raise HTTPException(400, f"Unsupported file type: {ext}. Only .dxf and .dwg files are supported.")

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"File too large ({size_mb:.1f}MB). Max is {MAX_FILE_SIZE_MB}MB.")

    drawing_id = str(uuid.uuid4())
    save_path = UPLOAD_DIR / f"{drawing_id}{ext}"
    save_path.write_bytes(contents)

    try:
        if ext == ".dxf":
            parse_result = parse_dxf_file(str(save_path))
        elif ext == ".dwg":
            parse_result = parse_dwg_file(str(save_path))
        else:
            raise HTTPException(400, f"Unsupported file type: {ext}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Failed to parse drawing: {str(e)}")

    # Legend-first architecture: return ALL blocks as raw symbols.
    # No dictionary labeling, no AI classification, no consolidation.
    # The legend matching step will identify and consolidate symbols later.
    all_raw_symbols = []
    for block in parse_result.ai_candidate_blocks:
        all_raw_symbols.append(SymbolInfo(
            block_name=block.block_name,
            label=block.block_name,  # Raw block name as label (will be replaced by matching)
            count=block.count,
            locations=block.locations,
            color="#999999",  # Neutral gray — matching will assign real colors
            confidence="pending",
            source="raw",
        ))
    # Also include fast-path symbols but strip their dictionary labels
    for sym in parse_result.fast_path_symbols:
        all_raw_symbols.append(SymbolInfo(
            block_name=sym.block_name,
            label=sym.block_name,  # Use raw block name, not dictionary label
            count=sym.count,
            locations=sym.locations,
            color="#999999",
            confidence="pending",
            source="raw",
        ))

    # Sort by count descending
    all_raw_symbols.sort(key=lambda s: -s.count)

    parse_result.analysis.append({
        "type": "info",
        "message": f"Found {len(all_raw_symbols)} unique blocks "
        f"({sum(s.count for s in all_raw_symbols)} total insertions) — "
        f"ready for legend matching",
    })

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
        symbols=all_raw_symbols,
        total_symbols=sum(s.count for s in all_raw_symbols),
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


@app.post("/api/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    if request.drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found. Please upload a drawing first.")

    drawing = drawings_store[request.drawing_id]

    # Build history from request
    history = None
    if request.history:
        history = [{"role": h.role, "content": h.content} for h in request.history]

    response_text = await chat_with_drawing(request.message, drawing, history)
    return ChatResponse(response=response_text)


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


# ── Legend Endpoints ──────────────────────────────────────────────────


@app.post("/api/legend/upload", response_model=LegendParseResponse)
async def upload_legend(file: UploadFile):
    """Upload a legend file (PDF or image) for AI-powered device extraction."""
    # Early check: API key must be set for legend parsing
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise HTTPException(
            500,
            "ANTHROPIC_API_KEY is not configured. "
            "Set it in the Render dashboard (or .env for local dev)."
        )

    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in ALL_LEGEND_EXTENSIONS:
        raise HTTPException(
            400,
            f"Unsupported file type: {ext}. Supported: {', '.join(sorted(ALL_LEGEND_EXTENSIONS))}",
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(400, f"File too large ({size_mb:.1f}MB). Max is {MAX_FILE_SIZE_MB}MB.")

    try:
        result = await parse_legend_file(contents, file.filename)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Legend parsing failed: {e}", exc_info=True)
        raise HTTPException(500, f"Failed to parse legend: {str(e)}")
    finally:
        del contents  # Free uploaded file bytes

    result.legend_id = str(uuid.uuid4())

    # Set category colors for legend devices (instant keyword matching)
    for device in result.devices:
        device.color = _get_symbol_color(device.name)

    legends_store[result.legend_id] = result
    return result


@app.get("/api/legend/{legend_id}", response_model=LegendParseResponse)
def get_legend(legend_id: str):
    if legend_id not in legends_store:
        raise HTTPException(404, "Legend not found")
    return legends_store[legend_id]


# ── Matching Endpoints ────────────────────────────────────────────────


from pydantic import BaseModel as PydanticBaseModel


class MatchLegendRequest(PydanticBaseModel):
    legend_id: str


@app.post("/api/drawings/{drawing_id}/match-legend")
async def match_drawing_to_legend(drawing_id: str, request: MatchLegendRequest):
    """Match detected drawing symbols to legend entries using AI.

    This enriches each SymbolInfo with its matched LegendDevice (including
    the detailed symbol_description needed for SVG icon generation).
    """
    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")
    if request.legend_id not in legends_store:
        raise HTTPException(404, "Legend not found")

    drawing = drawings_store[drawing_id]
    legend = legends_store[request.legend_id]

    # Collect analysis steps for this matching operation
    match_analysis: list[AnalysisStep] = []

    try:
        matches = await match_symbols_to_legend(
            symbols=drawing.symbols,
            legend_devices=legend.devices,
            analysis=match_analysis,
        )
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"Legend matching failed: {e}", exc_info=True)
        # Still append whatever analysis we got before the error
        drawing.analysis.extend(match_analysis)
        drawings_store[drawing_id] = drawing
        raise HTTPException(500, f"Matching failed: {str(e)}")

    # Apply matches to symbols — legend becomes the source of truth.
    # Matches are keyed by block_name (raw block names from DXF).
    matched_count = 0
    matched_symbols = []
    unmatched_symbols = []

    for sym in drawing.symbols:
        key = sym.block_name
        if key in matches and matches[key].device is not None:
            match_result = matches[key]
            device = match_result.device
            sym.matched_legend = device
            sym.match_confidence = match_result.confidence
            sym.original_label = sym.label  # Preserve raw block name for audit
            sym.label = device.name  # Legend name is now the label
            sym.source = "legend"
            sym.confidence = match_result.confidence
            sym.color = _get_symbol_color(device.name)
            matched_count += 1
            matched_symbols.append(sym)
        else:
            sym.matched_legend = None
            sym.match_confidence = None
            unmatched_symbols.append(sym)

    # Post-match consolidation: merge blocks matched to the same legend device.
    # e.g., blocks "SD-1", "SD_TYPE2", "SMOKE_DET" all matched to "Smoke Detector"
    # → merge into one "Smoke Detector" row with combined counts and locations.
    label_groups: dict[str, list[SymbolInfo]] = {}
    for sym in matched_symbols:
        label_groups.setdefault(sym.label, []).append(sym)

    consolidated = []
    for label, group in label_groups.items():
        if len(group) == 1:
            consolidated.append(group[0])
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
            best_confidence = max(
                group,
                key=lambda s: {"high": 3, "medium": 2, "low": 1}.get(s.confidence, 0)
            ).confidence
            consolidated.append(SymbolInfo(
                block_name=combined_name,
                label=label,
                count=total_count,
                locations=all_locations,
                color=group[0].color,
                confidence=best_confidence,
                source="legend",
                block_variants=block_names,
                matched_legend=group[0].matched_legend,
                match_confidence=group[0].match_confidence,
            ))

    # Sort consolidated (matched) by count descending, then append unmatched
    consolidated.sort(key=lambda s: -s.count)
    final_symbols = consolidated + sorted(unmatched_symbols, key=lambda s: -s.count)

    # Update the drawing in store
    drawing.symbols = final_symbols
    drawing.total_symbols = sum(s.count for s in final_symbols)
    drawing.analysis.extend(match_analysis)
    drawings_store[drawing_id] = drawing

    # Invalidate preview cache since symbols changed
    preview_cache.pop(drawing_id, None)

    return {
        "status": "ok",
        "matched": matched_count,
        "total_symbols": len(final_symbols),
        "unmatched": len(unmatched_symbols),
        "symbols": final_symbols,
        "analysis": match_analysis,
    }


# ── Icon Generation Endpoints ─────────────────────────────────────────


@app.post("/api/drawings/{drawing_id}/generate-icons")
async def generate_drawing_icons(drawing_id: str):
    """Generate SVG icons for all legend-matched symbols in a drawing.

    Requires that match-legend has been called first. For each symbol with
    a matched_legend entry, generates an SVG icon from the symbol_description.
    Icons are cached globally by device name.
    """
    if drawing_id not in drawings_store:
        raise HTTPException(404, "Drawing not found")

    drawing = drawings_store[drawing_id]

    # Collect devices that need icons
    devices_to_generate = []
    seen_names: set[str] = set()
    for sym in drawing.symbols:
        if sym.matched_legend and sym.matched_legend.name not in seen_names:
            devices_to_generate.append({
                "name": sym.matched_legend.name,
                "symbol_description": sym.matched_legend.symbol_description,
            })
            seen_names.add(sym.matched_legend.name)

    if not devices_to_generate:
        return {
            "status": "ok",
            "generated": 0,
            "total": 0,
            "message": "No legend-matched symbols to generate icons for",
            "symbols": drawing.symbols,
        }

    try:
        icons = await generate_icons_batch(devices_to_generate)
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(
            f"Icon generation failed: {e}", exc_info=True)
        raise HTTPException(500, f"Icon generation failed: {str(e)}")

    # Apply icons to symbols and their matched_legend entries
    icon_count = 0
    for sym in drawing.symbols:
        if sym.matched_legend and sym.matched_legend.name in icons:
            svg = icons[sym.matched_legend.name]
            sym.svg_icon = svg
            sym.matched_legend.svg_icon = svg
            icon_count += 1

    drawings_store[drawing_id] = drawing

    return {
        "status": "ok",
        "generated": len(icons),
        "total": len(devices_to_generate),
        "failed": len(devices_to_generate) - len(icons),
        "symbols": drawing.symbols,
    }


@app.get("/api/icons/{device_name}")
def get_icon(device_name: str):
    """Serve a cached SVG icon by device name."""
    from fastapi.responses import Response
    if device_name not in icons_cache:
        raise HTTPException(404, "Icon not found")
    return Response(
        content=icons_cache[device_name],
        media_type="image/svg+xml",
    )


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
