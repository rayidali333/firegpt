"""
Legend Parser — AI-powered construction drawing legend extraction.

Accepts PDF or image files containing construction drawing legends/symbol keys.
Uses Claude Vision API to identify every device entry, extract names,
abbreviations, categories, and detailed symbol descriptions.

The symbol descriptions are designed to be detailed enough for AI-based
SVG generation of each symbol icon.

Supports:
- Image files: PNG, JPG, JPEG, GIF, WEBP
- PDF files: converted to images via PyMuPDF at high DPI for symbol clarity
- Multi-page PDFs: all pages sent as separate images in one API call
"""

import base64
import io
import json
import logging
import math
import os
import re
import time

from anthropic import AsyncAnthropic

from app.models import AnalysisStep, LegendDevice, LegendParseResponse

logger = logging.getLogger(__name__)

# PDF rendering DPI — adaptive based on page size.
# We want 300 DPI for sharp symbols, but large pages at 300 DPI create
# pixmaps that exceed 512MB RAM on Render free tier.
# Strategy: calculate the pixmap size first, pick the highest DPI that fits.
PDF_RENDER_DPI_MAX = 400
PDF_RENDER_DPI_MIN = 150

# Tiling threshold — landscape pages whose pixel width at chosen DPI
# exceeds this are split into overlapping left/right tiles so Claude
# Vision sees each column at higher effective resolution.
TILE_WIDTH_THRESHOLD = 2500  # pixels
TILE_OVERLAP = 0.10          # 10% overlap at the seam

# Maximum pixmap memory budget per page (bytes).
# A pixel = 3 bytes (RGB, no alpha). Keep each pixmap under 80MB
# to leave headroom for Python + FastAPI + base64 + API request.
MAX_PIXMAP_BYTES = 80 * 1024 * 1024

# Maximum image dimension before resizing
MAX_IMAGE_DIMENSION = 2048

# Maximum total image payload size in bytes.
# Anthropic API allows up to 20MB per image.
MAX_IMAGE_BYTES = 15 * 1024 * 1024

# Supported file types
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
PDF_EXTENSIONS = {".pdf"}
ALL_LEGEND_EXTENSIONS = IMAGE_EXTENSIONS | PDF_EXTENSIONS

# MIME types for image content blocks
MIME_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}

# Claude model for legend analysis — Opus has superior vision accuracy
# and produces more detailed, precise symbol descriptions than Sonnet.
LEGEND_MODEL = "claude-opus-4-6"

# Max tokens for legend response — Opus writes more detailed descriptions
# per device (~200-250 tokens each), so 100+ devices need 25-35K tokens.
# 65K gives comfortable headroom for even the densest legends.
LEGEND_MAX_TOKENS = 65536

# Low temperature for precise, deterministic visual descriptions.
# We want exact shapes/fills/text, not creative variation.
LEGEND_TEMPERATURE = 0.2


def _get_client() -> AsyncAnthropic:
    """Get or create the Anthropic API client."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set. Add it to backend/.env")
    return AsyncAnthropic(api_key=api_key)


def _log(analysis: list[AnalysisStep], type: str, message: str):
    """Append an analysis step and log it."""
    analysis.append(AnalysisStep(type=type, message=message))
    log_fn = {"info": logger.info, "success": logger.info,
              "warning": logger.warning, "error": logger.error}.get(type, logger.info)
    log_fn(f"[Legend] {message}")


async def parse_legend_file(
    file_bytes: bytes,
    filename: str,
) -> LegendParseResponse:
    """Parse a legend file (PDF or image) using Claude Vision API.

    This is the main entry point. It:
    1. Validates the file and prepares image(s) for Claude
    2. Sends to Claude Vision with a detailed extraction prompt
    3. Parses the structured JSON response
    4. Returns a LegendParseResponse with devices, categories, and analysis log

    Args:
        file_bytes: Raw file content
        filename: Original filename (used for extension detection)

    Returns:
        LegendParseResponse with extracted devices and analysis log
    """
    analysis: list[AnalysisStep] = []
    ext = _get_extension(filename)
    file_size_mb = len(file_bytes) / (1024 * 1024)

    _log(analysis, "info", f"Legend file: {filename} ({file_size_mb:.1f} MB, {ext})")

    # Validate file type
    if ext not in ALL_LEGEND_EXTENSIONS:
        _log(analysis, "error",
             f"Unsupported file type: {ext}. Supported: PDF, PNG, JPG, GIF, WEBP")
        return _empty_response(filename, analysis)

    # Step 1: Prepare images for Claude Vision
    _log(analysis, "info", "Preparing images for AI analysis...")
    try:
        if ext in PDF_EXTENSIONS:
            images = _prepare_pdf_images(file_bytes, analysis)
        else:
            images = _prepare_single_image(file_bytes, ext, analysis)
    except Exception as e:
        _log(analysis, "error", f"Image preparation failed: {e}")
        return _empty_response(filename, analysis)
    finally:
        # Free raw file bytes — images are now in base64 form
        del file_bytes

    if not images:
        _log(analysis, "error", "No usable images could be extracted from the file")
        return _empty_response(filename, analysis)

    _log(analysis, "success",
         f"Prepared {len(images)} image(s) for analysis")

    # Step 2: Send to Claude Vision API
    _log(analysis, "info",
         f"Sending {len(images)} image(s) to Claude ({LEGEND_MODEL}) for legend analysis...")

    try:
        start_time = time.monotonic()
        devices, categories, notes = await _analyze_with_claude(images, filename, analysis)
        elapsed = time.monotonic() - start_time
        _log(analysis, "info", f"Claude responded in {elapsed:.1f}s")
    except Exception as e:
        _log(analysis, "error", f"Claude Vision analysis failed: {e}")
        return _empty_response(filename, analysis)

    # Step 3: Validate and log results
    if not devices:
        _log(analysis, "warning",
             "Claude did not identify any device entries in the legend. "
             "The file may not contain a readable legend, or the image quality "
             "may be too low.")
        return _empty_response(filename, analysis, notes=notes)

    # Log per-category breakdown
    cat_counts: dict[str, int] = {}
    for d in devices:
        cat_counts[d.category] = cat_counts.get(d.category, 0) + 1

    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        _log(analysis, "info", f"  {cat}: {count} device types")

    # Log devices with abbreviations for quick debugging
    abbrev_count = sum(1 for d in devices if d.abbreviation)
    _log(analysis, "info",
         f"Abbreviations found: {abbrev_count}/{len(devices)} devices have abbreviations")

    # Log ALL extracted devices to console for full visibility
    logger.info("=" * 70)
    logger.info("LEGEND EXTRACTION RESULTS — All detected devices:")
    logger.info("=" * 70)
    for i, d in enumerate(devices, 1):
        abbr = f" [{d.abbreviation}]" if d.abbreviation else ""
        logger.info(f"  {i:3d}. {d.name}{abbr}")
        logger.info(f"       Category: {d.category}")
        logger.info(f"       Symbol:   {d.symbol_description[:120]}")
    logger.info("=" * 70)
    logger.info(f"TOTAL: {len(devices)} device types across {len(cat_counts)} categories")
    logger.info("=" * 70)

    # Also add all devices to the analysis log so they show in the frontend
    _log(analysis, "info", "── Full device list ──")
    for i, d in enumerate(devices, 1):
        abbr = f" [{d.abbreviation}]" if d.abbreviation else ""
        _log(analysis, "info", f"  {i}. {d.name}{abbr} — {d.symbol_description[:100]}")

    _log(analysis, "success",
         f"Legend analysis complete: {len(devices)} device types "
         f"across {len(categories)} categories")

    return LegendParseResponse(
        legend_id="",  # Set by the endpoint
        filename=filename,
        devices=devices,
        categories_found=categories,
        total_device_types=len(devices),
        analysis=analysis,
        notes=notes or "",
    )


def _get_extension(filename: str) -> str:
    """Extract lowercase file extension."""
    dot_idx = filename.rfind(".")
    if dot_idx < 0:
        return ""
    return filename[dot_idx:].lower()


def _empty_response(
    filename: str,
    analysis: list[AnalysisStep],
    notes: str = "",
) -> LegendParseResponse:
    """Create an empty response for error/empty cases."""
    return LegendParseResponse(
        legend_id="",
        filename=filename,
        devices=[],
        categories_found=[],
        total_device_types=0,
        analysis=analysis,
        notes=notes,
    )


# ── Image preparation ──────────────────────────────────────────────────


def _prepare_pdf_images(
    file_bytes: bytes,
    analysis: list[AnalysisStep],
) -> list[dict]:
    """Convert PDF pages to high-resolution PNG images for Claude Vision.

    Uses PyMuPDF (fitz) to render each page at PDF_RENDER_DPI.
    Returns a list of image dicts with base64 data and metadata.
    """
    try:
        import fitz  # PyMuPDF
    except ImportError:
        _log(analysis, "error",
             "PyMuPDF (fitz) is not installed. Cannot process PDF files. "
             "Install with: pip install PyMuPDF")
        return []

    try:
        pdf_doc = fitz.open(stream=file_bytes, filetype="pdf")
    except Exception as e:
        _log(analysis, "error", f"Cannot open PDF: {e}")
        return []

    page_count = len(pdf_doc)
    _log(analysis, "info", f"PDF has {page_count} page(s)")

    if page_count == 0:
        _log(analysis, "warning", "PDF has no pages")
        return []

    # Limit to first 5 pages to stay within memory budget (512MB on Render free)
    max_pages = min(page_count, 5)
    if page_count > max_pages:
        _log(analysis, "warning",
             f"PDF has {page_count} pages — processing first {max_pages} only")

    images = []
    for page_num in range(max_pages):
        try:
            page = pdf_doc[page_num]
            rect = page.rect  # page size in points (72 points = 1 inch)
            page_w_in = rect.width / 72
            page_h_in = rect.height / 72

            # Calculate the highest DPI that keeps the pixmap under budget.
            # Pixmap bytes = width_px * height_px * 3 (RGB)
            # Solving for dpi: dpi = sqrt(MAX_PIXMAP_BYTES / (w * h * 3))
            max_dpi_for_budget = int(math.sqrt(
                MAX_PIXMAP_BYTES / (page_w_in * page_h_in * 3)
            ))
            chosen_dpi = max(PDF_RENDER_DPI_MIN,
                             min(PDF_RENDER_DPI_MAX, max_dpi_for_budget))

            est_px_w = int(page_w_in * chosen_dpi)
            est_px_h = int(page_h_in * chosen_dpi)
            is_landscape = rect.width > rect.height * 1.2

            # Decide whether to tile: landscape pages with wide pixel
            # dimensions benefit from splitting so Claude Vision sees
            # each column at higher effective resolution.
            should_tile = is_landscape and est_px_w > TILE_WIDTH_THRESHOLD

            if should_tile:
                # Split into left and right halves with overlap
                overlap_pts = rect.width * TILE_OVERLAP
                mid_pt = rect.width / 2

                clips = [
                    ("Left section", fitz.Rect(
                        rect.x0, rect.y0,
                        mid_pt + overlap_pts, rect.y1)),
                    ("Right section", fitz.Rect(
                        mid_pt - overlap_pts, rect.y0,
                        rect.x1, rect.y1)),
                ]

                _log(analysis, "info",
                     f"  Page {page_num + 1}: {page_w_in:.1f}×{page_h_in:.1f} in "
                     f"(landscape) → tiling into 2 halves at {chosen_dpi} DPI")

                for label, clip_rect in clips:
                    tile_images = _render_clip(
                        page, clip_rect, chosen_dpi, page_num, label, analysis)
                    if tile_images:
                        images.extend(tile_images)
            else:
                _log(analysis, "info",
                     f"  Page {page_num + 1}: {page_w_in:.1f}×{page_h_in:.1f} in "
                     f"→ {chosen_dpi} DPI "
                     f"({est_px_w}×{est_px_h}px)")

                rendered = _render_clip(
                    page, None, chosen_dpi, page_num, None, analysis)
                if rendered:
                    images.extend(rendered)

        except Exception as e:
            _log(analysis, "warning",
                 f"  Page {page_num + 1}: rendering failed — {e}")
            continue

    pdf_doc.close()
    return images


def _render_clip(
    page,
    clip_rect,
    dpi: int,
    page_num: int,
    label: str | None,
    analysis: list[AnalysisStep],
) -> list[dict]:
    """Render a page (or clipped region) to a PNG image dict.

    Args:
        page: fitz.Page object
        clip_rect: fitz.Rect to clip, or None for full page
        dpi: rendering DPI
        page_num: 0-based page index (for logging)
        label: optional tile label (e.g., "Left section")
        analysis: analysis log
    """
    import fitz  # noqa: F811 — re-import needed for type access

    mat = fitz.Matrix(dpi / 72, dpi / 72)
    kwargs = {"matrix": mat, "alpha": False}
    if clip_rect is not None:
        kwargs["clip"] = clip_rect

    pix = page.get_pixmap(**kwargs)
    width, height = pix.width, pix.height
    png_bytes = pix.tobytes("png")
    pix = None  # free pixmap immediately

    # Re-render at lower DPI if PNG exceeds API image size limit
    if len(png_bytes) > MAX_IMAGE_BYTES:
        lower_dpi = int(dpi * 0.75)
        tag = f" ({label})" if label else ""
        _log(analysis, "info",
             f"  Page {page_num + 1}{tag} PNG too large "
             f"({len(png_bytes) / 1024 / 1024:.1f}MB), "
             f"re-rendering at {lower_dpi} DPI")
        png_bytes = None
        mat = fitz.Matrix(lower_dpi / 72, lower_dpi / 72)
        kwargs["matrix"] = mat
        pix = page.get_pixmap(**kwargs)
        width, height = pix.width, pix.height
        png_bytes = pix.tobytes("png")
        pix = None

    b64 = base64.standard_b64encode(png_bytes).decode("ascii")
    png_bytes = None

    result = {
        "base64": b64,
        "media_type": "image/png",
        "width": width,
        "height": height,
        "page": page_num + 1,
    }
    if label:
        result["tile_label"] = label

    return [result]


def _prepare_single_image(
    file_bytes: bytes,
    ext: str,
    analysis: list[AnalysisStep],
) -> list[dict]:
    """Prepare a single image file for Claude Vision.

    Checks dimensions and file size. Resizes if necessary using PyMuPDF
    to avoid adding a Pillow dependency. Falls back to sending as-is if
    PyMuPDF is not available (the API will handle downscaling).
    """
    media_type = MIME_TYPES.get(ext, "image/png")
    size_mb = len(file_bytes) / (1024 * 1024)

    # Try to get image dimensions and resize if needed
    width, height = _get_image_dimensions(file_bytes, ext)
    if width and height:
        _log(analysis, "info", f"Image dimensions: {width}x{height}px")

        max_dim = max(width, height)
        if max_dim > MAX_IMAGE_DIMENSION or len(file_bytes) > MAX_IMAGE_BYTES:
            resized = _resize_image(file_bytes, ext, analysis)
            if resized:
                file_bytes = resized
                size_mb = len(file_bytes) / (1024 * 1024)
                _log(analysis, "info",
                     f"Resized image: {size_mb:.1f}MB")

    b64 = base64.standard_b64encode(file_bytes).decode("ascii")
    _log(analysis, "info", f"Image ready: {size_mb:.1f}MB, {media_type}")

    return [{
        "base64": b64,
        "media_type": media_type,
        "width": width or 0,
        "height": height or 0,
    }]


def _get_image_dimensions(file_bytes: bytes, ext: str) -> tuple[int, int]:
    """Get image width and height without external dependencies.

    Reads the header bytes of common image formats.
    Returns (width, height) or (0, 0) if unknown.
    """
    try:
        if ext in (".png",):
            # PNG: width at bytes 16-20, height at 20-24 (big-endian)
            if len(file_bytes) >= 24 and file_bytes[:4] == b'\x89PNG':
                w = int.from_bytes(file_bytes[16:20], 'big')
                h = int.from_bytes(file_bytes[20:24], 'big')
                return w, h

        elif ext in (".jpg", ".jpeg"):
            # JPEG: scan for SOF markers
            data = file_bytes
            i = 2
            while i < len(data) - 9:
                if data[i] != 0xFF:
                    break
                marker = data[i + 1]
                if marker in (0xC0, 0xC1, 0xC2):
                    h = int.from_bytes(data[i + 5:i + 7], 'big')
                    w = int.from_bytes(data[i + 7:i + 9], 'big')
                    return w, h
                length = int.from_bytes(data[i + 2:i + 4], 'big')
                i += 2 + length
    except Exception:
        pass
    return 0, 0


def _resize_image(
    file_bytes: bytes,
    ext: str,
    analysis: list[AnalysisStep],
) -> bytes | None:
    """Resize an image if it's too large, using PyMuPDF.

    Returns resized PNG bytes, or None if resizing is not possible.
    """
    try:
        import fitz
        # Open image as a single-page PDF document
        img_doc = fitz.open(stream=file_bytes, filetype=ext.lstrip("."))
        page = img_doc[0]
        rect = page.rect

        # Calculate scale to fit within MAX_IMAGE_DIMENSION
        max_dim = max(rect.width, rect.height)
        scale = min(1.0, MAX_IMAGE_DIMENSION / max_dim)

        if scale < 1.0:
            mat = fitz.Matrix(scale, scale)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            _log(analysis, "info",
                 f"Resized to {pix.width}x{pix.height}px (scale={scale:.2f})")
            png_bytes = pix.tobytes("png")
            img_doc.close()
            return png_bytes

        img_doc.close()
    except Exception as e:
        _log(analysis, "info", f"Image resize skipped (PyMuPDF: {e})")
    return None


# ── Claude Vision Analysis ──────────────────────────────────────────────


def _build_legend_prompt() -> str:
    """Build the analysis prompt for Claude Vision.

    This prompt is designed to be robust across different legend formats:
    - Single-system or multi-system legends
    - Legends in different languages
    - Dense or sparse layouts
    - With or without graphical symbols
    - Color or black-and-white
    """
    return """You are an expert at reading construction drawing legends, symbol keys, and device schedules used in MEP (Mechanical, Electrical, Plumbing) engineering drawings.

Analyze this legend image carefully and extract EVERY device/equipment entry you can find.

For EACH entry in the legend, provide:

1. "name": The full device name exactly as written in the legend (e.g., "Main Fire Alarm Control Panel", "Smoke Detector", "Manual Call Station Weatherproof"). Preserve the original text faithfully.

2. "abbreviation": Any abbreviation, code, or short label shown in or near the symbol (e.g., "MFACP", "SD", "MCS", "CR"). If the abbreviation is displayed inside the symbol graphic, extract it. Use null if no abbreviation is visible.

3. "category": The section/system header this entry belongs to (e.g., "Fire Alarm System", "Access Control System", "Structured Cabling System"). Use the exact section header text from the legend. If there are no section headers, use "General" as the category.

4. "symbol_description": A precise, SVG-reproducible visual description of the symbol/icon shown next to this entry. A graphic designer must be able to recreate the exact symbol from your description alone. Describe ALL of these aspects:

   REQUIRED — describe each one explicitly:
   - SHAPE: circle, square, rectangle, triangle, diamond, hexagon, octagon, or compound shape (e.g., "rectangle with triangular notch on right side")
   - SIZE: relative proportions (e.g., "square ~8mm", "tall rectangle ~6mm wide × 12mm tall")
   - FILL: solid black, white/hollow, hatched, cross-hatched, half-filled (specify which half: left/right/top/bottom), stippled, or a specific color
   - BORDER: thick black outline, thin outline, double-line border, dashed, dotted, rounded corners, or no border
   - TEXT INSIDE: exact letters, numbers, or codes rendered inside the shape (e.g., "contains uppercase 'SD' centered")
   - INTERNAL FEATURES: diagonal line, cross/X, dot, concentric circle, smaller shape nested inside, arrow, lightning bolt, wave pattern
   - EXTERNAL FEATURES: lines extending from specific sides, arrows, leader lines, connection ticks, antenna marks
   - DISTINGUISHING MARKS: what makes this symbol visually different from similar nearby symbols

   EXAMPLE of a GOOD description:
   "Small square (~8mm) with solid black fill and thin black border. Contains the white uppercase letters 'FACP' centered inside. Two short horizontal lines extend from the left and right sides, suggesting connection points."

   EXAMPLE of a BAD description (too vague — DO NOT do this):
   "Square with text inside"

   If no graphical symbol is shown (text-only entry), state: "No graphical symbol — text label only"
   If the symbol is too small or blurry to describe clearly, describe what you CAN see and note the uncertainty.

CRITICAL INSTRUCTIONS — COMPLETENESS IS THE TOP PRIORITY:
- Extract EVERY SINGLE entry in the legend. Do NOT skip any. Missing devices is the worst possible failure.
- Each line or row in the legend is typically a separate device type — count them all.
- Look for entries organized under section/category headers (bold text, underlined text, or visually separated groups).
- Some entries may span multiple lines of text — combine them into one entry.
- Include entries from ALL sections and systems (fire alarm, access control, CCTV, cabling, HVAC, BMS, PA/GA, LAN, SCADA, smart systems, audio visual, etc.).
- Do NOT skip entries that seem similar — "Manual Call Station" and "Manual Call Station Weatherproof" are DIFFERENT entries.
- If a single entry has multiple variant descriptions (e.g., with/without weatherproof), list each variant as a separate device.
- Read all text carefully — construction abbreviations can be subtle.
- If the legend spans multiple columns, read ALL columns from left to right, top to bottom. Dense legends often have 3-5 columns.
- After your first pass, go back and scan the image again to catch any entries you missed.
- Count your entries section by section and verify the total matches what you see.
- If the images are tiled sections of the same page, combine all entries into ONE response. Do NOT duplicate entries that appear in the overlap region.

Return ONLY a valid JSON object (no markdown code fences, no explanation before or after) with this exact structure:
{
  "devices": [
    {
      "name": "Full device name as written",
      "abbreviation": "CODE or null",
      "category": "Section/System Name",
      "symbol_description": "Detailed visual description of the symbol"
    }
  ],
  "categories_found": ["List", "of", "all", "section", "headers"],
  "total_device_types": 45,
  "notes": "Any observations about legend format, readability issues, sections that were hard to read, or entries you are uncertain about"
}"""


async def _analyze_with_claude(
    images: list[dict],
    filename: str,
    analysis: list[AnalysisStep],
) -> tuple[list[LegendDevice], list[str], str]:
    """Send images to Claude Vision and parse the response.

    Returns:
        Tuple of (devices, categories_found, notes)
    """
    client = _get_client()

    # Build the content blocks: images first, then the text prompt
    content: list[dict] = []

    for i, img in enumerate(images):
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": img["media_type"],
                "data": img["base64"],
            },
        })
        if len(images) > 1:
            tile_label = img.get("tile_label")
            if tile_label:
                label_text = (f"(Page {img['page']} — {tile_label}. "
                              "These tiles overlap slightly — do NOT "
                              "duplicate entries that appear in both.)")
            else:
                label_text = f"(Page {img.get('page', i + 1)} of {len(images)})"
            content.append({
                "type": "text",
                "text": label_text,
            })

    content.append({
        "type": "text",
        "text": _build_legend_prompt(),
    })

    total_b64_size = sum(len(img["base64"]) for img in images)
    _log(analysis, "info",
         f"Request payload: {len(images)} image(s), "
         f"~{total_b64_size / 1024 / 1024:.1f}MB base64")

    try:
        response = await client.messages.create(
            model=LEGEND_MODEL,
            max_tokens=LEGEND_MAX_TOKENS,
            temperature=LEGEND_TEMPERATURE,
            messages=[{"role": "user", "content": content}],
        )
    except Exception as e:
        _log(analysis, "error", f"Claude API call failed: {e}")
        raise

    # Extract the response text
    if not response.content or not response.content[0].text:
        _log(analysis, "error", "Claude returned an empty response")
        return [], [], ""

    response_text = response.content[0].text.strip()

    # Log token usage
    usage = response.usage
    _log(analysis, "info",
         f"Claude usage: {usage.input_tokens} input tokens, "
         f"{usage.output_tokens} output tokens")

    # Check if response was truncated
    if response.stop_reason == "max_tokens":
        _log(analysis, "warning",
             f"Response was truncated at {LEGEND_MAX_TOKENS} tokens — "
             "some devices may be missing. Consider splitting the legend.")

    # Parse JSON from response
    return _parse_legend_response(response_text, analysis)


def _parse_legend_response(
    response_text: str,
    analysis: list[AnalysisStep],
) -> tuple[list[LegendDevice], list[str], str]:
    """Parse Claude's JSON response into structured legend data.

    Handles:
    - Direct JSON
    - JSON wrapped in markdown code fences
    - JSON with leading/trailing text
    """
    json_text = _extract_json(response_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        _log(analysis, "error",
             f"Failed to parse Claude response as JSON: {e}")
        _log(analysis, "info",
             f"Response preview (first 500 chars): {response_text[:500]}")
        return [], [], ""

    # Validate top-level structure
    if not isinstance(data, dict):
        _log(analysis, "error",
             f"Expected JSON object, got {type(data).__name__}")
        return [], [], ""

    raw_devices = data.get("devices", [])
    categories = data.get("categories_found", [])
    total_claimed = data.get("total_device_types", 0)
    notes = data.get("notes", "")

    if not isinstance(raw_devices, list):
        _log(analysis, "error", "'devices' field is not a list")
        return [], [], notes

    # Parse each device entry
    devices: list[LegendDevice] = []
    parse_errors = 0

    for i, raw in enumerate(raw_devices):
        if not isinstance(raw, dict):
            parse_errors += 1
            continue

        name = str(raw.get("name", "")).strip()
        if not name:
            parse_errors += 1
            continue

        abbreviation = raw.get("abbreviation")
        if abbreviation is not None:
            abbreviation = str(abbreviation).strip()
            if not abbreviation or abbreviation.lower() == "null" or abbreviation.lower() == "none":
                abbreviation = None

        category = str(raw.get("category", "Uncategorized")).strip()
        symbol_description = str(raw.get("symbol_description", "")).strip()

        if not symbol_description:
            symbol_description = "No description provided"

        devices.append(LegendDevice(
            name=name,
            abbreviation=abbreviation,
            category=category,
            symbol_description=symbol_description,
        ))

    if parse_errors > 0:
        _log(analysis, "warning",
             f"Skipped {parse_errors} malformed device entries from AI response")

    # Verify count
    if total_claimed and abs(len(devices) - total_claimed) > 2:
        _log(analysis, "warning",
             f"Count mismatch: Claude claimed {total_claimed} devices "
             f"but returned {len(devices)} parseable entries")

    # Ensure categories list is complete
    actual_categories = sorted(set(d.category for d in devices))
    if set(actual_categories) != set(categories):
        _log(analysis, "info",
             "Categories list adjusted to match actual device categories")
        categories = actual_categories

    return devices, categories, notes


def _extract_json(text: str) -> str:
    """Extract JSON from a response that may contain markdown or surrounding text.

    Handles:
    - ```json ... ```
    - ``` ... ```
    - Direct JSON object
    - JSON preceded/followed by text
    """
    text = text.strip()

    # Try direct parse first
    if text.startswith("{"):
        return text

    # Handle markdown code blocks
    if "```" in text:
        # Find the JSON block
        patterns = [
            r'```json\s*\n(.*?)```',
            r'```\s*\n(.*?)```',
            r'```(.*?)```',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.DOTALL)
            if match:
                candidate = match.group(1).strip()
                if candidate.startswith("{"):
                    return candidate

    # Try to find a JSON object in the text
    brace_start = text.find("{")
    if brace_start >= 0:
        # Find the matching closing brace
        depth = 0
        for i in range(brace_start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start:i + 1]

    return text
