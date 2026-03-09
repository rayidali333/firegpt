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
from app.chat import chat_with_drawing, classify_blocks_with_ai, parse_legend_with_vision
from app.models import (
    AnalysisStep, AuditEntry, ChatRequest, ChatResponse, LegendData,
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
# Legend store — parsed legend data keyed by legend_id
legend_store: dict[str, LegendData] = {}
# Track which legend is associated with which drawing
drawing_legend_map: dict[str, str] = {}  # drawing_id → legend_id


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/upload-legend", response_model=LegendData)
async def upload_legend(file: UploadFile):
    """Upload a legend/key sheet (PDF or image) and parse it with Claude Vision."""
    if not file.filename:
        raise HTTPException(400, "No file provided")

    ext = Path(file.filename).suffix.lower()
    allowed_exts = {".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
    if ext not in allowed_exts:
        raise HTTPException(
            400,
            f"Unsupported file type: {ext}. "
            f"Legend must be an image ({', '.join(allowed_exts)})."
        )

    contents = await file.read()
    size_mb = len(contents) / (1024 * 1024)
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

    try:
        legend_data = await parse_legend_with_vision(
            image_data=contents,
            media_type=media_type,
            filename=file.filename,
        )
    except Exception as e:
        raise HTTPException(500, f"Failed to parse legend: {str(e)}")

    legend_store[legend_data.legend_id] = legend_data
    return legend_data


@app.post("/api/upload", response_model=ParseResponse)
async def upload_drawing(file: UploadFile, legend_id: str | None = None):
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

    # Resolve legend if provided
    legend = legend_store.get(legend_id) if legend_id else None

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

    # AI classification: send blocks to Claude for classification.
    # When legend is provided: ALL blocks go to AI with legend context (no fast-path).
    # When no legend: only ambiguous blocks go to AI (fast-path handles known patterns).
    blocks_to_classify = (
        parse_result.ai_candidate_blocks if not legend
        else parse_result.ai_candidate_blocks  # When legend present, parser sends ALL blocks as candidates
    )

    if blocks_to_classify:
        try:
            fast_path_labels = {
                s.block_name: s.label for s in parse_result.fast_path_symbols
            }

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

            if ai_labels:
                source_label = "legend + AI" if legend else "AI"
                parse_result.analysis.append({
                    "type": "success",
                    "message": f"{source_label} classified {len(ai_labels)} devices: "
                    + ", ".join(f'"{k}" → {v}' for k, v in list(ai_labels.items())[:8]),
                })

                for block in blocks_to_classify:
                    if block.block_name in ai_labels:
                        label = ai_labels[block.block_name]
                        confidence = "high" if legend else "medium"
                        source = "legend" if legend else "ai"
                        parse_result.symbols.append(
                            SymbolInfo(
                                block_name=block.block_name,
                                label=label,
                                count=block.count,
                                locations=block.locations,
                                color=_get_symbol_color(label),
                                confidence=confidence,
                                source=source,
                            )
                        )
                        parse_result.audit.append(AuditEntry(
                            block_name=block.block_name,
                            label=label,
                            count=block.count,
                            method="legend_ai" if legend else "ai",
                            confidence=confidence,
                            layers=block.layers,
                        ))
            else:
                n = len(blocks_to_classify)
                parse_result.analysis.append({
                    "type": "info",
                    "message": f"AI analyzed {n} blocks — none identified as devices",
                })
        except Exception:
            parse_result.analysis.append({
                "type": "warning",
                "message": "AI classification unavailable (no API key or service error)",
            })

    # Consolidate symbols by label — merge different block names that map to
    # the same device type (e.g., 4 different "Control Module" block variants
    # become one "Control Module" row with combined counts and locations).
    # Contractors need to see "Control Module: 35" not 4 separate rows.
    label_groups: dict[str, list[SymbolInfo]] = {}
    for sym in parse_result.symbols:
        label_groups.setdefault(sym.label, []).append(sym)

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
            # If any source is dictionary, mark as dictionary; otherwise ai
            sources = {s.source for s in group}
            best_source = "dictionary" if "dictionary" in sources else ("ai" if "ai" in sources else "manual")
            consolidated_symbols.append(SymbolInfo(
                block_name=combined_name,
                label=label,
                count=total_count,
                locations=all_locations,
                color=group[0].color,
                confidence=best_confidence,
                source=best_source,
                block_variants=block_names,
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
