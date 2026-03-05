import os
import uuid
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.parser import parse_dxf_file, parse_dwg_file, _get_symbol_color
from app.preview import generate_drawing_preview
from app.chat import chat_with_drawing, classify_blocks_with_ai
from app.models import (
    AnalysisStep, ChatRequest, ChatResponse, ParseResponse, PreviewResponse,
    SymbolInfo,
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

    # AI-first classification: send all ambiguous blocks to Claude with full
    # drawing context (layers, legend text, all block names, already-identified symbols).
    if parse_result.ai_candidate_blocks:
        try:
            # Build context of what fast-path already identified
            fast_path_labels = {
                s.block_name: s.label for s in parse_result.fast_path_symbols
            }

            ai_labels = await classify_blocks_with_ai(
                ai_candidate_blocks=parse_result.ai_candidate_blocks,
                filename=file.filename,
                all_block_names=parse_result.all_block_names,
                all_layer_names=parse_result.all_layer_names,
                fire_layers=parse_result.fire_layers,
                legend_texts=parse_result.legend_texts,
                fast_path_labels=fast_path_labels,
            )

            if ai_labels:
                parse_result.analysis.append({
                    "type": "success",
                    "message": f"AI classified {len(ai_labels)} fire alarm devices: "
                    + ", ".join(f'"{k}" → {v}' for k, v in list(ai_labels.items())[:8]),
                })

                for block in parse_result.ai_candidate_blocks:
                    if block.block_name in ai_labels:
                        label = ai_labels[block.block_name]
                        parse_result.symbols.append(
                            SymbolInfo(
                                block_name=block.block_name,
                                label=label,
                                count=block.count,
                                locations=block.locations,
                                color=_get_symbol_color(label),
                            )
                        )
            else:
                n = len(parse_result.ai_candidate_blocks)
                parse_result.analysis.append({
                    "type": "info",
                    "message": f"AI analyzed {n} blocks — none identified as fire alarm devices",
                })
        except Exception:
            parse_result.analysis.append({
                "type": "warning",
                "message": "AI classification unavailable (no API key or service error)",
            })

    # Convert analysis dicts to AnalysisStep models
    analysis_steps = [
        AnalysisStep(**step) for step in parse_result.analysis
    ]

    result = ParseResponse(
        drawing_id=drawing_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        symbols=parse_result.symbols,
        total_symbols=sum(s.count for s in parse_result.symbols),
        analysis=analysis_steps,
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
