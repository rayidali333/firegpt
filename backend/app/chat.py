"""
Chat module — LLM-powered Q&A and AI-first block classification.

The parsed symbol data is tiny (~2-5KB JSON), so we inject it directly
into the system prompt. No RAG or vector DB needed.

AI Classification: Instead of relying on hardcoded dictionaries and regex,
we send ALL ambiguous blocks to Claude with full drawing context — block names,
layers, attributes, legend text, geometry info — and let it classify them.
This works robustly across any naming convention, language, or CAD standard.
"""

import json
import logging
import os
import re

from anthropic import AsyncAnthropic

from app.models import LegendData, LegendSymbol, ParseResponse

logger = logging.getLogger(__name__)


def _extract_json_array(text: str) -> list:
    """Robustly extract a JSON array from LLM output.

    Handles markdown code blocks, surrounding prose, and trailing commas.
    """
    # Strategy 1: Try parsing the raw text directly
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from markdown code block (```json ... ``` or ``` ... ```)
    code_block_match = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    if code_block_match:
        block = code_block_match.group(1).strip()
        # Fix trailing commas
        block = re.sub(r',\s*([}\]])', r'\1', block)
        try:
            result = json.loads(block)
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find the outermost [ ... ] in the text
    # Use bracket matching to find the correct closing bracket
    start = text.find('[')
    if start != -1:
        depth = 0
        end = -1
        for i in range(start, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end != -1:
            array_text = text[start:end + 1]
            # Fix trailing commas
            array_text = re.sub(r',\s*([}\]])', r'\1', array_text)
            try:
                return json.loads(array_text)
            except json.JSONDecodeError:
                pass

    # Strategy 4: Handle truncated JSON — extract all complete {...} objects
    # This happens when the AI response hits max_tokens mid-array
    if start != -1:
        objects = []
        obj_depth = 0
        obj_start = -1
        in_string = False
        escape_next = False
        for i in range(start + 1, len(text)):
            ch = text[i]
            if escape_next:
                escape_next = False
                continue
            if ch == '\\' and in_string:
                escape_next = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch == '{':
                if obj_depth == 0:
                    obj_start = i
                obj_depth += 1
            elif ch == '}':
                obj_depth -= 1
                if obj_depth == 0 and obj_start != -1:
                    try:
                        obj = json.loads(text[obj_start:i + 1])
                        objects.append(obj)
                    except json.JSONDecodeError:
                        pass
                    obj_start = -1
        if objects:
            logger.warning(
                f"Recovered {len(objects)} complete objects from truncated JSON"
            )
            return objects

    raise ValueError(
        f"Could not extract JSON array from AI response. "
        f"Response starts with: {text[:200]!r}"
    )

client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to backend/.env"
            )
        client = AsyncAnthropic(api_key=api_key)
    return client


def _correct_legend_shape(sym: LegendSymbol) -> LegendSymbol:
    """Apply fire alarm industry domain knowledge to correct AI shape classifications.

    AI vision models often confuse pentagon (5 sides) vs hexagon (6 sides).
    In fire alarm drawings, detectors are universally hexagons per NFPA standards.
    This function overrides unreliable AI shape_code with correct industry shapes.
    """
    name_lower = sym.name.lower()
    category_lower = sym.category.lower()

    # Fire alarm detectors → HEXAGON (industry standard, AI often says "pentagon")
    detector_keywords = [
        "smoke detector", "heat detector", "detector", "photoelectric",
        "smoke and heat", "multi-sensor", "duct detector", "beam detector",
        "aspirating", "linear heat",
    ]
    if any(kw in name_lower for kw in detector_keywords):
        if sym.shape_code in ("pentagon", "hexagon", "circle"):
            old = sym.shape_code
            sym.shape_code = "hexagon"
            if old != "hexagon":
                logger.info(f"Shape correction: '{sym.name}' {old} → hexagon (detector)")

    # Panels, modules in boxes → SQUARE (rectangle)
    panel_keywords = [
        "control panel", "panel", "rack", "workstation", "converter",
    ]
    if any(kw in name_lower for kw in panel_keywords):
        if sym.shape_code not in ("square",):
            old = sym.shape_code
            sym.shape_code = "square"
            if old != "square":
                logger.info(f"Shape correction: '{sym.name}' {old} → square (panel/rack)")

    # Signal/control modules with text codes in rectangles → SQUARE
    module_rect_keywords = ["signal control module", "scm", "lhcp"]
    if any(kw in name_lower for kw in module_rect_keywords):
        sym.shape_code = "square"

    # Manual call station / pull station → SQUARE
    manual_keywords = ["manual call", "pull station", "break glass"]
    if any(kw in name_lower for kw in manual_keywords):
        sym.shape_code = "square"

    # Speakers / loudspeakers → CIRCLE
    speaker_keywords = ["speaker", "loudspeaker"]
    if any(kw in name_lower for kw in speaker_keywords):
        sym.shape_code = "circle"

    # Horn strobe / strobe / siren → STAR (distinctive shape)
    strobe_keywords = ["strobe", "siren"]
    if any(kw in name_lower for kw in strobe_keywords) and "horn" not in name_lower:
        sym.shape_code = "star"

    # Horn strobe combo → STAR
    if "horn" in name_lower and "strobe" in name_lower:
        sym.shape_code = "star"

    # Camera → DIAMOND
    camera_keywords = ["camera", "cctv"]
    if any(kw in name_lower for kw in camera_keywords):
        if sym.shape_code not in ("square",):
            sym.shape_code = "diamond"

    # Access control with text codes in rounded rectangles → SQUARE
    if category_lower == "access control":
        if sym.shape_code not in ("circle", "diamond"):
            sym.shape_code = "square"

    return sym


def _sanitize_svg(svg: str) -> str:
    """Sanitize AI-generated SVG to prevent XSS and normalize for embedding."""
    # Remove script tags
    svg = re.sub(r'<script[^>]*>.*?</script>', '', svg, flags=re.DOTALL | re.IGNORECASE)
    # Remove event handlers (onclick, onload, onerror, etc.)
    svg = re.sub(r'\s+on\w+\s*=\s*["\'][^"\']*["\']', '', svg, flags=re.IGNORECASE)
    # Remove javascript: URLs
    svg = re.sub(r'javascript\s*:', '', svg, flags=re.IGNORECASE)
    # Remove external references
    svg = re.sub(r'href\s*=\s*["\']https?://[^"\']*["\']', '', svg, flags=re.IGNORECASE)
    # Remove width/height from <svg> tag so CSS can control sizing
    svg = re.sub(r'(<svg[^>]*?)\s+width\s*=\s*["\'][^"\']*["\']', r'\1', svg, flags=re.IGNORECASE)
    svg = re.sub(r'(<svg[^>]*?)\s+height\s*=\s*["\'][^"\']*["\']', r'\1', svg, flags=re.IGNORECASE)
    return svg.strip()


async def _generate_symbol_svgs(symbols: list[LegendSymbol]) -> list[LegendSymbol]:
    """Generate SVG icons for each legend symbol using AI text model.

    Takes the shape descriptions from the vision-parsed legend and generates
    clean, monochrome SVG icons that match the actual legend symbols.
    Uses currentColor so the frontend can apply per-symbol colors.
    """
    if not symbols or not os.getenv("ANTHROPIC_API_KEY"):
        return symbols

    api_client = _get_client()
    BATCH_SIZE = 35  # Keep output within token limits

    for batch_start in range(0, len(symbols), BATCH_SIZE):
        batch = symbols[batch_start:batch_start + BATCH_SIZE]

        # Build descriptions from the vision-parsed data
        descriptions = []
        for i, sym in enumerate(batch):
            desc = f'{i + 1}. Code: "{sym.code}", Name: "{sym.name}"'
            if sym.shape:
                desc += f', Visual: {sym.shape}'
            else:
                desc += f', Shape: {sym.shape_code}'
            if sym.filled:
                desc += ' — FILLED/SOLID (shape is solid black)'
            else:
                desc += ' — OUTLINE ONLY'
            descriptions.append(desc)

        desc_text = "\n".join(descriptions)

        prompt = f"""Generate a minimal SVG icon for each construction drawing legend symbol described below.

STRICT RULES:
- Each SVG MUST have: viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg"
- Use ONLY: <polygon>, <circle>, <rect>, <text>, <line>, <path>, <ellipse>, <g>, <polyline>
- For OUTLINE shapes: stroke="currentColor" stroke-width="1.5" fill="none"
- For FILLED/SOLID shapes: fill="currentColor" stroke="currentColor" stroke-width="0.5"
- For text inside shapes: font-size appropriate for text length (1 char=10, 2-3 chars=8, 4+=6), font-weight="bold", text-anchor="middle", dominant-baseline="central"
- On OUTLINE shapes: text fill="currentColor"
- On FILLED shapes: text fill="white" (for contrast against solid fill)
- Center everything in the 24x24 viewBox
- These are engineering schematic symbols — keep them clean and precise
- NO <style>, <script>, <defs>, <filter>, <image>, <use>, <foreignObject>
- Each SVG must be ONE COMPLETE self-contained <svg>...</svg> element

SHAPE REFERENCE (use these as guides):
- Hexagon centered at (12,12), radius ~10: points at 30° intervals
- Rectangle: <rect> with rx="1" for slight rounding
- Circle: <circle cx="12" cy="12" r="10">
- Square: <rect x="2" y="2" width="20" height="20">
- Speaker icon: circle with concentric arcs or smaller circle inside
- Strobe: star or radiating lines from center
- Camera: trapezoid + rectangle (side view) or simplified icon

SYMBOLS TO GENERATE:
{desc_text}

Respond with ONLY a JSON object mapping the 1-based index number (as string) to the complete SVG string.
Example: {{"1": "<svg viewBox=\\"0 0 24 24\\" xmlns=\\"http://www.w3.org/2000/svg\\"><circle cx=\\"12\\" cy=\\"12\\" r=\\"10\\" stroke=\\"currentColor\\" fill=\\"none\\" stroke-width=\\"1.5\\"/><text x=\\"12\\" y=\\"12\\" text-anchor=\\"middle\\" dominant-baseline=\\"central\\" fill=\\"currentColor\\" font-size=\\"10\\" font-weight=\\"bold\\">S</text></svg>"}}"""

        try:
            logger.info(
                f"Generating SVG icons for symbols {batch_start + 1}-{batch_start + len(batch)} "
                f"of {len(symbols)}..."
            )
            response = await api_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )

            response_text = response.content[0].text.strip()

            if response.stop_reason == "max_tokens":
                logger.warning("SVG generation response was truncated (hit max_tokens)")

            # Extract JSON from response (handle markdown code blocks)
            if response_text.startswith("```"):
                lines = response_text.split("\n")
                json_lines = []
                in_block = False
                for line in lines:
                    if line.startswith("```") and not in_block:
                        in_block = True
                        continue
                    if line.startswith("```") and in_block:
                        break
                    if in_block:
                        json_lines.append(line)
                response_text = "\n".join(json_lines)

            result = json.loads(response_text)

            # Map SVGs back to batch symbols
            svg_count = 0
            for i, sym in enumerate(batch):
                key = str(i + 1)
                if key in result:
                    svg = _sanitize_svg(str(result[key]))
                    if svg.startswith("<svg"):
                        sym.svg_icon = svg
                        svg_count += 1

            logger.info(f"  Generated {svg_count}/{len(batch)} SVG icons in this batch")

        except json.JSONDecodeError as e:
            logger.warning(f"SVG generation returned invalid JSON (non-fatal): {e}")
        except Exception as e:
            logger.warning(f"SVG generation failed (non-fatal): {type(e).__name__}: {e}")

    total_with_svg = sum(1 for s in symbols if s.svg_icon)
    logger.info(f"SVG icon generation complete: {total_with_svg}/{len(symbols)} symbols have icons")
    return symbols


# ────────────────────────────────────────────────────────
# Legend parsing — page-by-page PDF extraction pipeline
# ────────────────────────────────────────────────────────

# Shared extraction rules for the legend parsing prompt.
# Kept as a constant so both per-page and single-page prompts are identical
# in their field definitions and shape guidance.
_LEGEND_FIELD_RULES = """For each symbol row, provide:
1. "code": The EXACT text shown INSIDE the symbol shape. Read it carefully character by character.
   - If the symbol contains text like "MFACP", "SCM", "LHCP", "S", "H", "TJ", "CR", "DS" — use EXACTLY that text.
   - For subscript variants, append the subscript: e.g., "S" with subscript "WP" → "SWP", or "S" with subscript "80" → "S80"
   - If the symbol is purely graphical (no text inside), describe what you see: e.g., "smoke_heat_combo" for a combined detector icon.
   - Do NOT make up codes. Only use what you can actually read in the image.
   - IMPORTANT: Each code must be UNIQUE. If you already extracted a symbol with code "H", do NOT extract another symbol with the same code "H" — re-read the image carefully to distinguish them.
2. "name": The full device name exactly as written next to the symbol (e.g., "Main Fire Alarm Control Panel", "Proximity Card Reader", "Addressable Input Module Weatherproof")
3. "category": The system category it belongs to. Use EXACTLY one of these:
   - "Fire Alarm" — detectors, panels, modules, manual stations, sirens, strobes, telephone, cables
   - "Access Control" — card readers, door locks, exit buttons, break glass, barriers, intercoms, biometric
   - "Structured Cabling" — server racks, patch panels, data outlets, switches, routers, UPS
   - "BMS" — building management system panels, workstations, converters, I/O panels
   - "Video Surveillance" — CCTV cameras, workstations, NVR, video management
   - "Public Address" — speakers, amplifiers, microphones, alarm racks, loudspeakers
   - "Other" — anything that doesn't fit above
4. "shape": Describe the visual shape precisely. Count the number of sides carefully:
   - 3 sides = triangle
   - 4 sides (equal) = square
   - 4 sides (rectangular) = rectangle
   - 5 sides = pentagon
   - 6 sides = hexagon (VERY COMMON for fire alarm detectors — count carefully!)
   - Round = circle
   Examples: "hexagon with S inside", "rectangle with MFACP text", "filled hexagon", "small square", "circle with concentric rings (speaker)", "rectangle with radiating lines (strobe)"
5. "shape_code": The OUTER shape. Count sides carefully. Use EXACTLY one of:
   - "circle" — circles, round shapes, ovals
   - "square" — squares, rectangles, boxes
   - "diamond" — diamond/rotated squares
   - "pentagon" — pentagons (exactly 5 sides)
   - "hexagon" — hexagons (exactly 6 sides) — fire alarm detectors are almost always hexagons!
   - "triangle" — triangles (exactly 3 sides)
   - "star" — star shapes, asterisk-like
6. "filled": true if the symbol shape is filled/solid black, false if it is just an outline

IMPORTANT SHAPE GUIDANCE:
- Fire alarm DETECTORS (smoke, heat, multi-sensor) almost always use HEXAGONS (6 sides). Count carefully!
- Panels and modules in rectangles/boxes → "square"
- Manual call stations / pull stations → "square"
- If you're unsure between pentagon and hexagon, it's almost certainly a HEXAGON in fire alarm drawings."""


def _get_pdf_page_count(pdf_bytes: bytes) -> int:
    """Return the number of pages in a PDF. Returns 1 if pymupdf is unavailable."""
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed — cannot count PDF pages. pip install PyMuPDF")
        return 1
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        count = len(doc)
        doc.close()
        return count
    except Exception as e:
        logger.warning(f"Failed to read PDF page count: {e}")
        return 1


def _split_pdf_to_pages(pdf_bytes: bytes) -> list[tuple[bytes, int]]:
    """Split a multi-page PDF into individual single-page PDFs.

    Each page is extracted as a separate PDF document (not rendered to PNG)
    to preserve full vector text quality. This is critical for reading small
    legend codes, subscripts, and fine text that gets lost in rasterization.

    Returns a list of (single_page_pdf_bytes, 1-indexed page_number) tuples.
    Falls back to empty list if pymupdf is unavailable or the PDF is unreadable.
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed — cannot split PDF pages")
        return []

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        logger.error(f"Failed to open PDF for page splitting: {e}")
        return []

    pages: list[tuple[bytes, int]] = []
    try:
        for page_idx in range(len(doc)):
            # Extract as a separate single-page PDF (preserves vector text quality)
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_idx, to_page=page_idx)
            page_pdf_bytes = new_doc.tobytes()
            new_doc.close()
            pages.append((page_pdf_bytes, page_idx + 1))
            logger.info(
                f"  PDF page {page_idx + 1}/{len(doc)}: "
                f"{len(page_pdf_bytes) / 1024:.0f}KB single-page PDF"
            )
    finally:
        doc.close()

    return pages


def _build_content_block(image_data: bytes, media_type: str) -> dict:
    """Build the Anthropic API content block for an image or PDF document."""
    import base64
    data_b64 = base64.standard_b64encode(image_data).decode("utf-8")

    if media_type == "application/pdf":
        return {
            "type": "document",
            "source": {"type": "base64", "media_type": media_type, "data": data_b64},
        }
    return {
        "type": "image",
        "source": {"type": "base64", "media_type": media_type, "data": data_b64},
    }


async def _extract_symbols_from_page(
    api_client: AsyncAnthropic,
    image_data: bytes,
    media_type: str,
    page_context: str,
    max_tokens: int = 32768,
    prompt_variant: str = "default",
) -> list[dict]:
    """Extract symbol definitions from a single legend page or image.

    Args:
        api_client: Initialized Anthropic async client.
        image_data: Raw bytes of the image or single-page PDF.
        media_type: MIME type ("image/png", "application/pdf", etc.).
        page_context: Human-readable context, e.g. "page 2 of 3" or "".
        max_tokens: Maximum output tokens for the API call.
        prompt_variant: Extraction strategy — "default", "bottom_up", or "section_by_section".

    Returns:
        List of raw symbol dicts (not yet converted to LegendSymbol).
    """
    # Build page-aware prompt header
    if page_context:
        header = (
            f"You are analyzing {page_context} of a construction drawing legend/key sheet.\n\n"
            "CRITICAL: Extract ONLY the symbols visible on THIS page. "
            "Do not guess or infer symbols that might be on other pages."
        )
    else:
        header = (
            "You are analyzing a construction drawing legend/key sheet. "
            "Your task is to extract EVERY SINGLE symbol definition shown — do NOT skip any rows."
        )

    # Variant-specific scanning instructions
    if prompt_variant == "bottom_up":
        scan_instruction = (
            "SCANNING ORDER: Start from the BOTTOM of the page and work UPWARD. "
            "Read the LAST section first, then the second-to-last, and so on until you reach the top. "
            "This ensures you don't miss entries at the bottom of the page."
        )
    elif prompt_variant == "section_by_section":
        scan_instruction = (
            "SCANNING ORDER: First, list ALL section headers you see on this page. "
            "Then process each section one at a time, counting the rows in each section BEFORE extracting. "
            "After extracting all sections, verify your total matches the sum of your per-section counts."
        )
    else:
        scan_instruction = (
            "BEFORE YOU START: Scan the entire legend and count the total number of symbol rows across ALL sections. "
            "Then extract every single one. Your JSON array should have that exact number of entries."
        )

    prompt = f"""{header}

CRITICAL RULES:
- Extract ONLY symbols that are LITERALLY VISIBLE as distinct rows in this legend image.
- Do NOT invent, assume, or infer symbols that are not explicitly drawn and labeled.
- Do NOT assume weatherproof variants exist unless you can clearly see them as separate rows.
- Do NOT generate devices from general fire alarm knowledge — only from what is on the page.
- Each ROW in the legend is a SEPARATE symbol, even if two rows look similar.
- If a symbol code has a small subscript letter (like S with subscript "80"), include it (e.g., code="S80").
- If two symbols have the same shape but different descriptions, they are TWO separate entries.
- If you are UNSURE whether a row exists, DO NOT include it.
- Count EVERY row in EVERY section. Do NOT summarize or group similar entries.
- Process ALL system sections visible: Fire Alarm, Access Control, BMS, Video Surveillance, Structured Cabling, Public Address, and any others.

{_LEGEND_FIELD_RULES}

{scan_instruction}

Respond with ONLY a JSON array:
[{{"code": "S", "name": "Smoke Detector", "category": "Fire Alarm", "shape": "hexagon with S inside", "shape_code": "hexagon", "filled": false}}, ...]"""

    content_block = _build_content_block(image_data, media_type)

    log_label = f"[{page_context}] " if page_context else ""
    variant_label = f" ({prompt_variant})" if prompt_variant != "default" else ""
    logger.info(
        f"  {log_label}Sending {media_type} to Claude{variant_label} "
        f"(max_tokens={max_tokens})..."
    )

    try:
        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": prompt}],
            }],
        )
    except Exception as api_err:
        logger.error(f"  {log_label}Claude API call failed: {type(api_err).__name__}: {api_err}")
        raise

    logger.info(
        f"  {log_label}Response{variant_label}: stop_reason={response.stop_reason}, "
        f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
    )

    was_truncated = response.stop_reason == "max_tokens"
    if was_truncated:
        logger.warning(f"  {log_label}Response TRUNCATED (hit max_tokens={max_tokens})")

    if not response.content:
        logger.error(f"  {log_label}Claude returned empty content")
        return []

    response_text = response.content[0].text.strip()
    logger.info(f"  {log_label}Response length: {len(response_text)} chars")

    try:
        raw_symbols = _extract_json_array(response_text)
    except (ValueError, json.JSONDecodeError) as e:
        logger.error(f"  {log_label}JSON extraction failed: {e}")
        logger.error(f"  {log_label}Response (first 500): {response_text[:500]}")
        return []

    logger.info(f"  {log_label}Extracted {len(raw_symbols)} symbols{variant_label}")

    # ── Truncation recovery: if truncated, retry once with 2x budget ──
    if was_truncated and max_tokens < 65536:
        retry_budget = min(max_tokens * 2, 65536)
        logger.info(
            f"  {log_label}Retrying truncated extraction with "
            f"max_tokens={retry_budget}..."
        )
        retry_symbols = await _extract_symbols_from_page(
            api_client, image_data, media_type, page_context,
            max_tokens=retry_budget,
            prompt_variant=prompt_variant,
        )
        # Use whichever attempt returned more symbols
        if len(retry_symbols) > len(raw_symbols):
            logger.info(
                f"  {log_label}Retry improved: {len(raw_symbols)} → {len(retry_symbols)} symbols"
            )
            return retry_symbols
        logger.info(
            f"  {log_label}Retry did not improve ({len(retry_symbols)} vs {len(raw_symbols)}), "
            f"keeping original"
        )

    return raw_symbols


async def _multi_pass_extract_page(
    api_client: AsyncAnthropic,
    image_data: bytes,
    media_type: str,
    page_context: str,
) -> list[dict]:
    """Run multiple extraction passes with varied prompts, then union the results.

    Each pass uses a different scanning strategy (top-down, bottom-up,
    section-by-section) to catch symbols that any single pass might miss due
    to attention drift on dense pages. Results are merged by (code, name)
    deduplication — first occurrence wins.

    Returns the union of all passes (deduplicated).
    """
    log_label = f"[{page_context}] " if page_context else ""

    # Pass 1: default top-down scan
    pass1 = await _extract_symbols_from_page(
        api_client, image_data, media_type, page_context,
        prompt_variant="default",
    )
    logger.info(f"  {log_label}Multi-pass: pass 1 (default) → {len(pass1)} symbols")

    # Pass 2: bottom-up scan — catches symbols at the bottom that top-down misses
    pass2 = await _extract_symbols_from_page(
        api_client, image_data, media_type, page_context,
        prompt_variant="bottom_up",
    )
    logger.info(f"  {log_label}Multi-pass: pass 2 (bottom_up) → {len(pass2)} symbols")

    # Pass 3: section-by-section — forces explicit section counting before extraction
    pass3 = await _extract_symbols_from_page(
        api_client, image_data, media_type, page_context,
        prompt_variant="section_by_section",
    )
    logger.info(f"  {log_label}Multi-pass: pass 3 (section_by_section) → {len(pass3)} symbols")

    # Union all passes — deduplicate by (code, name)
    union = _deduplicate_symbols(pass1 + pass2 + pass3)

    # Log what extra symbols the additional passes found
    pass1_codes = {(s.get("code", "").upper().strip(), s.get("name", "").upper().strip()) for s in pass1}
    new_from_pass2 = [s for s in pass2 if (s.get("code", "").upper().strip(), s.get("name", "").upper().strip()) not in pass1_codes]
    all_so_far = pass1_codes | {(s.get("code", "").upper().strip(), s.get("name", "").upper().strip()) for s in pass2}
    new_from_pass3 = [s for s in pass3 if (s.get("code", "").upper().strip(), s.get("name", "").upper().strip()) not in all_so_far]

    if new_from_pass2:
        logger.info(
            f"  {log_label}Multi-pass: pass 2 found {len(new_from_pass2)} NEW symbols: "
            + ", ".join(f'"{s.get("code", "")}"' for s in new_from_pass2[:10])
        )
    if new_from_pass3:
        logger.info(
            f"  {log_label}Multi-pass: pass 3 found {len(new_from_pass3)} NEW symbols: "
            + ", ".join(f'"{s.get("code", "")}"' for s in new_from_pass3[:10])
        )

    logger.info(
        f"  {log_label}Multi-pass union: {len(pass1)} + {len(new_from_pass2)} + {len(new_from_pass3)} "
        f"= {len(union)} unique symbols"
    )
    return union


def _render_page_to_crops(page_pdf_bytes: bytes, dpi: int = 300) -> list[tuple[bytes, str]]:
    """Render a single-page PDF into overlapping half-page PNG crops.

    Splits the page into top-half and bottom-half with 15% overlap in the
    middle to avoid cutting through symbol rows. Higher DPI than the full-page
    render makes small text and subscripts more legible.

    Returns list of (png_bytes, region_label) tuples.
    """
    try:
        import fitz
    except ImportError:
        logger.warning("PyMuPDF not installed — cannot render page crops")
        return []

    try:
        doc = fitz.open(stream=page_pdf_bytes, filetype="pdf")
        page = doc[0]
        rect = page.rect
        page_height = rect.height

        # Define overlapping regions: top 57.5% and bottom 57.5% (15% overlap)
        overlap_fraction = 0.15
        top_clip = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + page_height * (0.5 + overlap_fraction / 2))
        bottom_clip = fitz.Rect(rect.x0, rect.y0 + page_height * (0.5 - overlap_fraction / 2), rect.x1, rect.y1)

        crops = []
        for clip, label in [(top_clip, "top-half"), (bottom_clip, "bottom-half")]:
            mat = fitz.Matrix(dpi / 72, dpi / 72)
            pix = page.get_pixmap(matrix=mat, clip=clip)
            png_bytes = pix.tobytes("png")
            crops.append((png_bytes, label))

        doc.close()
        return crops
    except Exception as e:
        logger.warning(f"Failed to render page crops: {e}")
        return []


async def _cropped_extraction_pass(
    api_client: AsyncAnthropic,
    page_pdf_bytes: bytes,
    page_context: str,
    existing_symbols: list[dict],
) -> list[dict]:
    """Extract symbols from high-res cropped regions of a page.

    Renders the page into overlapping top/bottom halves at high DPI, then
    extracts from each crop. Deduplicates against already-known symbols and
    returns only genuinely new ones.
    """
    log_label = f"[{page_context}] " if page_context else ""

    crops = _render_page_to_crops(page_pdf_bytes)
    if not crops:
        return []

    existing_keys = {
        (s.get("code", "").upper().strip(), s.get("name", "").upper().strip())
        for s in existing_symbols
    }

    all_crop_symbols: list[dict] = []
    for crop_bytes, region_label in crops:
        crop_context = f"{page_context} {region_label}" if page_context else region_label
        crop_symbols = await _extract_symbols_from_page(
            api_client, crop_bytes, "image/png", crop_context,
        )
        logger.info(f"  {log_label}Crop ({region_label}): {len(crop_symbols)} symbols")
        all_crop_symbols.extend(crop_symbols)

    # Deduplicate crop results internally
    crop_unique = _deduplicate_symbols(all_crop_symbols)

    # Filter to only genuinely new symbols
    new_symbols = [
        s for s in crop_unique
        if (s.get("code", "").upper().strip(), s.get("name", "").upper().strip()) not in existing_keys
    ]

    if new_symbols:
        logger.info(
            f"  {log_label}Crop extraction found {len(new_symbols)} NEW symbols: "
            + ", ".join(f'"{s.get("code", "")}"' for s in new_symbols[:10])
        )
    else:
        logger.info(f"  {log_label}Crop extraction found no new symbols beyond existing {len(existing_symbols)}")

    return new_symbols


def _deduplicate_symbols(symbols: list[dict]) -> list[dict]:
    """Remove duplicate symbols by (code, name) pair AND detect code collisions.

    - Exact (code, name) duplicates: second occurrence is dropped.
    - Code collisions (same code, different name): second occurrence is dropped
      and logged as a warning, since legend codes should be unique.
    Preserves insertion order — the first occurrence wins.
    """
    seen: set[tuple[str, str]] = set()
    seen_codes: dict[str, str] = {}  # code -> first name seen
    unique: list[dict] = []
    for sym in symbols:
        code = sym.get("code", "").upper().strip()
        name = sym.get("name", "").upper().strip()
        key = (code, name)
        if key in seen:
            continue
        # Check for code collision (same code, different name)
        if code and code in seen_codes and seen_codes[code] != name:
            logger.warning(
                f"Dedup: code collision — code '{code}' used by both "
                f"'{seen_codes[code]}' and '{name}'. Keeping first."
            )
            continue
        seen.add(key)
        if code:
            seen_codes[code] = name
        unique.append(sym)
    return unique


def _extract_json_object(text: str) -> dict:
    """Robustly extract a JSON object from LLM response text.

    Handles markdown code blocks, surrounding prose, and common output formats.
    """
    text = text.strip()

    # Strategy 1: direct parse
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except json.JSONDecodeError:
        pass

    # Strategy 2: strip markdown code fences
    if "```" in text:
        match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group(1).strip())
                if isinstance(result, dict):
                    return result
            except json.JSONDecodeError:
                pass

    # Strategy 3: find outermost { }
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not extract JSON object from response (first 200 chars): {text[:200]}")


# Standard category names used in extraction prompts. Pre-scan maps
# raw legend section headers to these so counts are directly comparable.
_STANDARD_CATEGORIES = [
    "Fire Alarm", "Access Control", "Structured Cabling",
    "BMS", "Video Surveillance", "Public Address", "Other",
]


async def _prescan_section_counts(
    api_client: AsyncAnthropic,
    image_data: bytes,
    media_type: str,
) -> dict[str, int] | None:
    """Quick pre-scan to count symbol rows per section in the legend.

    Sends the full PDF/image and asks Claude to ONLY count (not extract).
    Counting is much easier than full extraction, so this is highly reliable.

    Returns dict mapping category name to expected count, or None on failure.
    """
    categories_str = ", ".join(f'"{c}"' for c in _STANDARD_CATEGORIES)

    prompt = f"""Look at this construction drawing legend/key sheet.

Your ONLY task is to count the number of distinct SYMBOL ROWS in each system section.

Rules for counting:
- Each row with a symbol graphic + text description = 1 symbol row
- Only count rows that are ACTUALLY VISIBLE — do not estimate or assume
- If a section has rows you cannot clearly read, count only the ones you can see
- Cable/line symbols ARE rows (count them!)
- Section headers, column headers, notes, and title blocks are NOT symbol rows

Map each section to one of these standard categories:
{categories_str}

If multiple sections map to the same category, combine their counts.
If a section doesn't fit any category, use "Other".

Output ONLY a JSON object mapping category to count:
{{"Fire Alarm": 42, "Access Control": 18, "Video Surveillance": 12}}"""

    content_block = _build_content_block(image_data, media_type)

    logger.info("Pre-scan: counting sections and symbols per section...")

    try:
        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": prompt}],
            }],
        )
    except Exception as e:
        logger.warning(f"Pre-scan failed (non-fatal): {e}")
        return None

    logger.info(
        f"Pre-scan response: stop_reason={response.stop_reason}, "
        f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
    )

    if not response.content:
        logger.warning("Pre-scan returned empty content")
        return None

    response_text = response.content[0].text.strip()

    try:
        counts = _extract_json_object(response_text)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Pre-scan JSON parsing failed: {e}")
        return None

    # Validate: all values should be positive integers
    validated: dict[str, int] = {}
    for section, count in counts.items():
        try:
            n = int(count)
            if n > 0:
                validated[section] = n
        except (TypeError, ValueError):
            logger.warning(f"Pre-scan: ignoring invalid count for '{section}': {count}")

    total = sum(validated.values())
    logger.info(
        f"Pre-scan complete: {total} total symbols across {len(validated)} sections — "
        + ", ".join(f"{k}: {v}" for k, v in sorted(validated.items()))
    )
    return validated


async def _reconciliation_pass(
    api_client: AsyncAnthropic,
    extracted: list[dict],
    original_data: bytes,
    original_media_type: str,
    target_counts: dict[str, int] | None = None,
) -> list[dict]:
    """Verify extraction completeness and find missed symbols.

    When target_counts is provided (from pre-scan), builds a gap-focused prompt
    that tells Claude exactly which sections have missing symbols and how many.
    This is far more effective than the generic "find what I missed" approach.

    When target_counts is None, falls back to the generic section-by-section
    verification prompt.
    """
    # Group extracted symbols by category
    by_category: dict[str, list[dict]] = {}
    for sym in extracted:
        cat = sym.get("category", "Other")
        by_category.setdefault(cat, []).append(sym)

    # ── Build the prompt ──
    if target_counts:
        # Gap-aware reconciliation: compare extracted vs expected per section
        # Apply 10% tolerance — pre-scan counts are estimates, not ground truth
        comparison_lines = []
        gap_sections: list[tuple[str, int, int, int]] = []  # (cat, expected, actual, missing)

        # Merge all section names from both sources
        all_sections = sorted(set(list(target_counts.keys()) + list(by_category.keys())))

        for section in all_sections:
            expected = target_counts.get(section, 0)
            actual = len(by_category.get(section, []))
            # Allow 10% tolerance — if we're within 90% of expected, consider it OK
            # (tighter than before since multi-pass extraction gets closer to target)
            tolerance_threshold = max(1, int(expected * 0.90))
            if actual < tolerance_threshold:
                gap = expected - actual
                gap_sections.append((section, expected, actual, gap))
                comparison_lines.append(f"  [{section}] extracted: {actual}, expected: ~{expected} — ⚠ MISSING ~{gap}")
            elif expected > 0:
                comparison_lines.append(f"  [{section}] extracted: {actual}, expected: ~{expected} — ✓ OK")
            elif actual > 0 and expected == 0:
                comparison_lines.append(f"  [{section}] extracted: {actual} (not in pre-scan)")

        total_missing = sum(g[3] for g in gap_sections)

        if total_missing == 0:
            logger.info("Gap analysis: no significant gaps detected (within 15% tolerance)")
            return extracted

        # Build detailed gap info with already-extracted symbols for context
        gap_details = []
        for section, expected, actual, missing in gap_sections:
            syms = by_category.get(section, [])
            sym_list = "\n".join(
                f'    {i+1}. code="{s.get("code", "")}" — "{s.get("name", "")}"'
                for i, s in enumerate(syms)
            )
            gap_details.append(
                f'\n[{section}] — I have {actual}/{expected} ({missing} MISSING):'
                f'\n  Already extracted:\n{sym_list if sym_list else "    (none)"}'
            )

        prompt = f"""I extracted {len(extracted)} symbols from this legend, but I'm MISSING {total_missing} based on row counts.

Section comparison:
{chr(10).join(comparison_lines)}

Details for sections with GAPS:
{"".join(gap_details)}

TASK: For each section marked as MISSING above, carefully examine the legend and find the specific symbol rows I missed.
- Look row by row in each section, comparing against my "Already extracted" list
- Only add symbols you can ACTUALLY SEE as distinct rows with a visible symbol graphic and text label
- Do NOT invent devices from general fire alarm knowledge
- Do NOT assume weatherproof or other variants exist — only add them if you can clearly see them as separate rows
- Do NOT add symbols just to reach the expected count — the expected counts are ESTIMATES and may be wrong
- Each code MUST be unique — do not add a symbol with a code that already exists in my extracted list
- It is BETTER to return fewer symbols than to hallucinate entries that don't exist

Return ONLY a JSON array of the missing symbols:
[{{"code": "...", "name": "...", "category": "...", "shape": "...", "shape_code": "...", "filled": false}}, ...]

If you cannot find any genuinely missing symbols, return: []"""

        logger.info(
            f"Targeted reconciliation: {total_missing} symbols missing across "
            f"{len(gap_sections)} sections — "
            + ", ".join(f"{s}: {m} missing" for s, _, _, m in gap_sections)
        )
    else:
        # Generic reconciliation (no pre-scan data available)
        category_lines = []
        for cat in sorted(by_category.keys()):
            syms = by_category[cat]
            category_lines.append(f"\n[{cat}] — {len(syms)} symbols extracted:")
            for i, s in enumerate(syms):
                category_lines.append(
                    f'  {i+1}. code="{s.get("code", "")}" — "{s.get("name", "")}"'
                )
        summary = "\n".join(category_lines)

        prompt = f"""I extracted {len(extracted)} symbols from this legend, grouped by system section:
{summary}

TASK — Section-by-section verification:
For EACH section header visible in the legend image:
1. Count the actual number of symbol rows in that section
2. Compare to the count I extracted above
3. If my count is LOWER, identify the specific rows I missed

Pay special attention to:
- Weatherproof variants (same device + "WEATHERPROOF" suffix)
- Subscript/suffix variants (small text like WP, T, F, P after the main code)
- Devices at the very bottom of columns or at page edges
- Cable/line symbols that look different from the boxed/shaped device symbols
- Sections I may have missed entirely

IMPORTANT: Only add symbols you can ACTUALLY SEE as distinct rows with a visible symbol graphic and text label.
- Do NOT add devices from general fire alarm knowledge
- Do NOT assume weatherproof or other variants exist unless you can clearly see them
- Do NOT decompose one entry's description into sub-devices
- Each code MUST be unique — do not add a symbol with a code already in my list
- It is BETTER to return fewer symbols than to hallucinate entries that don't exist

If you find missed symbols, return them as a JSON array:
[{{"code": "...", "name": "...", "category": "...", "shape": "...", "shape_code": "...", "filled": false}}, ...]

If nothing was missed, return an empty array: []

Respond with ONLY the JSON array."""

        logger.info(
            f"Generic reconciliation: verifying {len(extracted)} symbols "
            f"across {len(by_category)} categories..."
        )

    # ── Send to Claude ──
    content_block = _build_content_block(original_data, original_media_type)

    try:
        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=32768,
            messages=[{
                "role": "user",
                "content": [content_block, {"type": "text", "text": prompt}],
            }],
        )
    except Exception as e:
        logger.warning(f"Reconciliation API call failed (non-fatal): {e}")
        return extracted

    logger.info(
        f"Reconciliation response: stop_reason={response.stop_reason}, "
        f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
    )

    if not response.content:
        logger.warning("Reconciliation returned empty content")
        return extracted

    response_text = response.content[0].text.strip()

    try:
        missed = _extract_json_array(response_text)
    except (ValueError, json.JSONDecodeError) as e:
        logger.warning(f"Reconciliation JSON parsing failed (non-fatal): {e}")
        return extracted

    if not missed:
        logger.info("Reconciliation confirmed: no missed symbols")
        return extracted

    # Deduplicate against existing — also check for code collisions
    existing_keys = {
        (s.get("code", "").upper().strip(), s.get("name", "").upper().strip())
        for s in extracted
    }
    existing_codes = {
        s.get("code", "").upper().strip() for s in extracted
    }
    # Cap reconciliation additions at 20% of current count to prevent runaway hallucination
    max_additions = max(5, len(extracted) // 5)
    added = 0
    skipped_code_collision = 0
    for entry in missed:
        if added >= max_additions:
            logger.warning(
                f"Reconciliation hit addition cap ({max_additions}), "
                f"skipping remaining {len(missed) - added} candidates"
            )
            break
        code_upper = entry.get("code", "").upper().strip()
        name_upper = entry.get("name", "").upper().strip()
        key = (code_upper, name_upper)
        if key in existing_keys:
            continue
        # Reject if code already exists (collision)
        if code_upper and code_upper in existing_codes:
            skipped_code_collision += 1
            logger.info(
                f"Reconciliation: skipping code collision '{code_upper}' "
                f"('{entry.get('name', '')}' vs existing)"
            )
            continue
        extracted.append(entry)
        existing_keys.add(key)
        existing_codes.add(code_upper)
        added += 1

    logger.info(
        f"Reconciliation found {len(missed)} candidates, "
        f"added {added} new (after dedup, {skipped_code_collision} code collisions skipped). "
        f"Total: {len(extracted)}"
    )
    return extracted


async def parse_legend_with_vision(
    image_data: bytes,
    media_type: str,
    filename: str,
) -> LegendData:
    """Parse a legend sheet image/PDF into structured symbol data using Claude Vision.

    Pipeline:
      0. Pre-scan: count symbols per section for ground-truth verification targets.
      1. For multi-page PDFs: split into pages.
      2. Multi-pass extraction: run 3 varied prompts per page (top-down, bottom-up,
         section-by-section) and union results to catch attention-drift misses.
      3. Merge and deduplicate across pages.
      4. Gap check: if extracted count is still below pre-scan target, run high-res
         cropped extraction (top/bottom halves at 300 DPI) to recover small-text symbols.
      5. Gap-targeted reconciliation: compare extracted counts against pre-scan
         targets, then ask Claude to find the specific missing rows.
      6. Convert raw dicts to LegendSymbol with domain-knowledge shape corrections.
      7. Generate SVG icons for each symbol.
    """
    import uuid

    logger.info("=== parse_legend_with_vision START ===")
    logger.info(
        f"Filename: {filename}, media_type: {media_type}, "
        f"data_size: {len(image_data)} bytes"
    )

    api_client = _get_client()

    # ── Step 0: Pre-scan section counts ──
    # Quick pass to count symbols per section. Gives us ground-truth targets
    # for the reconciliation pass. Counting is cheap (~200 output tokens).
    target_counts: dict[str, int] | None = None
    try:
        target_counts = await _prescan_section_counts(
            api_client, image_data, media_type,
        )
    except Exception as prescan_err:
        logger.warning(
            f"Pre-scan failed (non-fatal): {type(prescan_err).__name__}: {prescan_err}"
        )

    # ── Step 1: Determine processing strategy ──
    is_pdf = media_type == "application/pdf"
    page_count = _get_pdf_page_count(image_data) if is_pdf else 1
    is_multi_page = is_pdf and page_count > 1

    logger.info(
        f"Strategy: {'multi-page PDF (' + str(page_count) + ' pages)' if is_multi_page else 'single page/image'}"
    )

    # ── Step 2: Multi-pass extraction ──
    # Each page gets 3 extraction passes with varied prompts (top-down, bottom-up,
    # section-by-section). The union catches symbols that any single pass misses.
    all_raw_symbols: list[dict] = []
    # Keep per-page PDF bytes for potential crop pass later
    page_pdf_map: list[tuple[bytes, str]] = []  # (pdf_bytes, page_context)

    if is_multi_page:
        page_pdfs = _split_pdf_to_pages(image_data)

        if not page_pdfs:
            logger.warning(
                "PDF page splitting failed — falling back to single-shot multi-pass extraction"
            )
            page_symbols = await _multi_pass_extract_page(
                api_client, image_data, media_type, page_context="",
            )
            all_raw_symbols = page_symbols
        else:
            for page_data, page_num in page_pdfs:
                page_context = f"page {page_num} of {page_count}"
                page_symbols = await _multi_pass_extract_page(
                    api_client, page_data, "application/pdf", page_context,
                )
                logger.info(
                    f"  Page {page_num}: multi-pass extracted {len(page_symbols)} symbols"
                )
                all_raw_symbols.extend(page_symbols)
                page_pdf_map.append((page_data, page_context))

            logger.info(
                f"All pages complete: {len(all_raw_symbols)} raw symbols "
                f"across {page_count} pages (multi-pass)"
            )
    else:
        # Single page PDF or image — multi-pass extraction
        all_raw_symbols = await _multi_pass_extract_page(
            api_client, image_data, media_type, page_context="",
        )
        if is_pdf:
            page_pdf_map.append((image_data, ""))

    if not all_raw_symbols:
        logger.error("No symbols extracted from any page")
        raise ValueError("Legend parsing produced no symbols")

    # ── Step 3: Deduplicate across pages ──
    pre_dedup_count = len(all_raw_symbols)
    unique_symbols = _deduplicate_symbols(all_raw_symbols)
    dedup_removed = pre_dedup_count - len(unique_symbols)
    if dedup_removed > 0:
        logger.info(
            f"Deduplication: {pre_dedup_count} → {len(unique_symbols)} "
            f"({dedup_removed} duplicates removed)"
        )
    else:
        logger.info(f"Deduplication: {len(unique_symbols)} symbols (no duplicates)")

    # ── Step 4: Cropped extraction for dense pages ──
    # If we have pre-scan targets and are still significantly below them,
    # render each page as high-res top/bottom crops and extract again.
    # This catches small text and symbols lost at full-page resolution.
    if target_counts and page_pdf_map:
        expected_total = sum(target_counts.values())
        current_total = len(unique_symbols)
        gap_pct = (expected_total - current_total) / max(expected_total, 1)
        if gap_pct > 0.08:  # More than 8% gap — worth trying crops
            logger.info(
                f"Crop pass triggered: {current_total}/{expected_total} symbols "
                f"({gap_pct:.0%} gap). Rendering high-res crops..."
            )
            for page_data, page_ctx in page_pdf_map:
                try:
                    new_from_crops = await _cropped_extraction_pass(
                        api_client, page_data, page_ctx, unique_symbols,
                    )
                    if new_from_crops:
                        unique_symbols.extend(new_from_crops)
                        unique_symbols = _deduplicate_symbols(unique_symbols)
                except Exception as crop_err:
                    logger.warning(
                        f"Crop extraction failed for {page_ctx} (non-fatal): "
                        f"{type(crop_err).__name__}: {crop_err}"
                    )
            logger.info(
                f"After crop pass: {len(unique_symbols)} symbols "
                f"(was {current_total})"
            )
        else:
            logger.info(
                f"Crop pass skipped: {current_total}/{expected_total} symbols "
                f"({gap_pct:.0%} gap — within 8% tolerance)"
            )

    # ── Step 5: Reconciliation pass ──
    # When pre-scan target counts are available, this does a targeted gap-fill:
    # compares extracted per-category counts against targets, then asks Claude
    # to find the specific missing rows in each under-extracted section.
    # Without targets, falls back to generic section-by-section verification.
    try:
        unique_symbols = await _reconciliation_pass(
            api_client, unique_symbols, image_data, media_type,
            target_counts=target_counts,
        )
    except Exception as recon_err:
        logger.warning(
            f"Reconciliation pass failed (non-fatal): "
            f"{type(recon_err).__name__}: {recon_err}"
        )

    # ── Step 6: Post-extraction validation ──
    # Final dedup pass after reconciliation (catches code collisions from recon)
    unique_symbols = _deduplicate_symbols(unique_symbols)

    # Remove entries with empty/missing codes or names
    pre_validation = len(unique_symbols)
    unique_symbols = [
        s for s in unique_symbols
        if s.get("code", "").strip() and s.get("name", "").strip()
    ]
    if len(unique_symbols) < pre_validation:
        logger.info(
            f"Validation: removed {pre_validation - len(unique_symbols)} entries "
            f"with empty code or name"
        )

    # ── Step 7: Convert to LegendSymbol + shape correction ──
    symbols: list[LegendSymbol] = []
    for i, entry in enumerate(unique_symbols):
        try:
            sym = LegendSymbol(
                code=entry.get("code", ""),
                name=entry.get("name", ""),
                category=entry.get("category", "Other"),
                shape=entry.get("shape", ""),
                shape_code=entry.get("shape_code", "circle"),
                filled=bool(entry.get("filled", False)),
            )
            sym = _correct_legend_shape(sym)
            symbols.append(sym)
        except Exception as sym_err:
            logger.warning(f"Failed to parse symbol entry {i}: {entry} — {sym_err}")

    # ── Step 8: Generate SVG icons ──
    systems = sorted(set(s.category for s in symbols))
    logger.info(
        f"Legend extraction complete: {len(symbols)} symbols "
        f"across {len(systems)} systems: {systems}"
    )

    try:
        symbols = await _generate_symbol_svgs(symbols)
    except Exception as svg_err:
        logger.warning(f"SVG icon generation failed (non-fatal): {svg_err}")

    # ── Step 9: Return ──
    legend_id = str(uuid.uuid4())
    return LegendData(
        legend_id=legend_id,
        filename=filename,
        symbols=symbols,
        total_symbols=len(symbols),
        systems=systems,
    )


async def classify_blocks_with_ai(
    ai_candidate_blocks: list,
    filename: str,
    all_block_names: list[str],
    all_layer_names: list[str],
    fire_layers: list[str],
    legend_texts: list[str],
    fast_path_labels: dict[str, str],
    legend: LegendData | None = None,
) -> dict[str, str]:
    """Use Claude to classify blocks that dictionary matching couldn't identify.

    When a legend is provided, ALL blocks are sent to AI for classification using
    the legend as the authoritative source of truth. The hardcoded dictionary is
    bypassed entirely — the legend defines what symbols exist in this project.

    When no legend is provided, falls back to the standard approach with hardcoded
    patterns and general AI classification.

    Args:
        ai_candidate_blocks: Blocks with full metadata that need classification
        filename: Original drawing filename
        all_block_names: Every block name in the drawing (for naming pattern context)
        all_layer_names: Every layer name (for understanding drawing organization)
        fire_layers: Layers identified as fire-alarm related
        legend_texts: Text from drawing legends/schedules
        fast_path_labels: Blocks already identified by dictionary (for context)
        legend: Optional parsed legend data from uploaded legend sheet

    Returns:
        dict mapping block_name -> label for blocks identified as fire alarm devices.
        Blocks identified as non-fire-alarm return empty dict entry (excluded).
    """
    if not ai_candidate_blocks:
        return {}

    if not os.getenv("ANTHROPIC_API_KEY"):
        return {}

    # Build structured metadata for each candidate block.
    # For sub-grouped blocks (same block_name, different attrib values),
    # use a composite key so the AI can return distinct labels per sub-group.
    blocks_data = []
    # Map composite keys back to original block info for response parsing
    composite_key_map: dict[str, tuple[str, str, str]] = {}  # composite_key → (block_name, sub_tag, sub_value)

    for block in ai_candidate_blocks:
        # Use composite key for sub-grouped blocks to avoid key collisions
        if block.sub_group_value:
            display_key = f"{block.block_name}|{block.sub_group_tag}={block.sub_group_value}"
            composite_key_map[display_key] = (block.block_name, block.sub_group_tag, block.sub_group_value)
        else:
            display_key = block.block_name

        entry = {
            "block_name": display_key,
            "count": block.count,
            "layers": block.layers,
        }
        if block.sub_group_value:
            entry["instance_attribute"] = f"{block.sub_group_tag}={block.sub_group_value}"
        if block.entity_types:
            entry["geometry_inside"] = block.entity_types
        if block.attribs:
            entry["insert_attributes"] = block.attribs
        if block.attdef_tags:
            entry["definition_attributes"] = block.attdef_tags
        if block.texts_inside:
            entry["text_labels_inside"] = block.texts_inside
        if block.description:
            entry["description"] = block.description
        blocks_data.append(entry)

    # ── Build shared prompt parts (same for all batches) ──

    # Build rich drawing context
    context_parts = []
    context_parts.append(f'Drawing file: "{filename}"')

    if fast_path_labels and not legend:
        context_parts.append(
            f"\nALREADY IDENTIFIED (by standard abbreviations):\n"
            + "\n".join(f'  - "{name}" = {label}' for name, label in fast_path_labels.items())
        )

    if all_layer_names:
        context_parts.append(f"\nALL LAYERS ({len(all_layer_names)}):\n{', '.join(all_layer_names)}")

    if fire_layers:
        context_parts.append(f"\nFIRE-RELATED LAYERS: {', '.join(fire_layers)}")

    if all_block_names:
        context_parts.append(f"\nALL BLOCK NAMES ({len(all_block_names)}):\n{', '.join(all_block_names)}")

    if legend_texts:
        context_parts.append(
            f"\nLEGEND/SCHEDULE TEXT FROM DRAWING ({len(legend_texts)} items):\n"
            + "\n".join(f'  "{t}"' for t in legend_texts[:30])
        )

    drawing_context = "\n".join(context_parts)

    # Legend-specific prompt parts (reused across batches)
    legend_entries = ""
    valid_labels_json = ""
    if legend:
        valid_labels = []
        legend_entries_lines = []
        for idx, s in enumerate(legend.symbols):
            valid_labels.append(s.name)
            legend_entries_lines.append(
                f'  {idx+1}. Code: "{s.code}" → "{s.name}" [{s.category}]'
            )
        legend_entries = "\n".join(legend_entries_lines)
        valid_labels_json = json.dumps(valid_labels)

    def _build_prompt(batch_blocks_json: str) -> str:
        """Build the classification prompt for a batch of blocks."""
        if legend:
            return f"""You are a fire alarm and building systems expert analyzing a CAD construction drawing.

You have been provided with the OFFICIAL LEGEND/KEY for this project. Use it as the AUTHORITATIVE
source of truth to classify every block in the drawing.

PROJECT LEGEND (from "{legend.filename}"):
{legend_entries}

DRAWING CONTEXT:
{drawing_context}

BLOCKS TO CLASSIFY:
{batch_blocks_json}

CLASSIFICATION RULES:
1. The legend above is the ONLY valid source. You MUST use the EXACT name string from the legend.
2. VALID LABELS (you MUST use one of these exact strings, or null):
   {valid_labels_json}
3. DO NOT invent, rephrase, or paraphrase device names. Use the legend name VERBATIM.
   - If the legend says "Heat Detector", you must return "Heat Detector", NOT "Temperature Detector"
   - If the legend says "Manual Call Station", NOT "Pull Station" or "Manual Pull Station"
   - If the legend says "Fire Alarm Siren", NOT "Alarm Siren" or "Siren"
4. Match blocks to legend entries by:
   - Block name containing the legend code (e.g., block "FA_MFACP_01" matches legend code "MFACP")
   - Text labels inside the block matching legend codes
   - Block attributes matching legend codes or names
   - Layer names suggesting the system category
5. Title blocks, sheet frames, borders, furniture, structural elements = null
6. When in doubt, classify as null. False negatives are better than false positives.

Respond with ONLY a JSON object mapping block names to EXACT legend names or null:
{{"block_name_1": "Heat Detector", "block_name_2": null, ...}}"""
        else:
            return f"""You are a fire alarm systems expert analyzing a CAD construction drawing.

Your job: classify each unidentified block as either a fire alarm / building safety device,
or as NOT a fire alarm device (furniture, plumbing, structural, annotation, etc.).

DRAWING CONTEXT:
{drawing_context}

BLOCKS TO CLASSIFY:
{batch_blocks_json}

CLASSIFICATION GUIDELINES:
1. Use the drawing's naming convention — look at already-identified blocks and layer names
   to understand patterns (e.g., if "FA-SD" = Smoke Detector, then "FA-HS" is likely Horn/Strobe)
2. Layer names are strong signals: blocks on "FIRE ALARM" or "FA-" layers are likely fire devices
3. Legend/schedule text maps symbol names to descriptions — use this as ground truth
4. Text labels inside blocks (like "SD", "HD") are definitive identifiers
5. Block attributes (TYPE, DEVICE, NAME) often contain the device identity
6. Block description fields are reliable when present
7. Geometry alone is NOT sufficient — many non-fire blocks also use circles/lines
8. When in doubt, classify as null (not a fire device). False negatives are better than false positives.

STANDARD FIRE ALARM LABELS (use these exact strings):
- Detection: "Smoke Detector", "Heat Detector", "Duct Detector", "Beam Detector",
  "Aspirating Smoke Detector", "Multi-Sensor Detector", "Fire Detector"
- Manual: "Pull Station", "Manual Call Point", "Break Glass"
- Notification: "Horn/Strobe", "Horn", "Strobe", "Speaker", "Alarm Siren"
- Control: "Fire Alarm Control Panel", "Annunciator", "Monitor Module",
  "Control Module", "Relay Module", "Monitor/Control Module"
- Suppression: "Sprinkler", "Fire Extinguisher", "Fire Cabinet"
- Infrastructure: "Junction Box", "Terminal Box", "End of Line"
- Safety: "Emergency Light", "Exit Sign", "Emergency Exit Sign",
  "Fire Door Holder", "Fire Hydrant", "Fire Hose", "Fire Pump"

IMPORTANT:
- "SPK" in fire alarm context = Speaker (voice evacuation), NOT Sprinkler
- Title blocks, sheet frames, borders = null
- Furniture, doors, windows, plumbing = null
- If a block appears hundreds of times and is NOT on a fire layer, it's likely NOT fire alarm

Respond with ONLY a JSON object. Fire devices get their label, everything else gets null:
{{"block_name_1": "Smoke Detector", "block_name_2": null, ...}}"""

    # ── Split blocks into batches ──
    # Large block sets overwhelm Claude — it can't produce valid JSON for 60+ mappings
    # in one response. Batches of ~20 are reliable and if one fails, others succeed.
    BATCH_SIZE = 20
    batches = [blocks_data[i:i + BATCH_SIZE] for i in range(0, len(blocks_data), BATCH_SIZE)]

    api_client = _get_client()
    all_identified: dict[str, str] = {}
    total_null = 0

    logger.info(
        f"=== AI BLOCK CLASSIFICATION START ===\n"
        f"  Blocks to classify: {len(blocks_data)}\n"
        f"  Legend: {'yes (' + str(len(legend.symbols)) + ' symbols)' if legend else 'no'}\n"
        f"  Batches: {len(batches)} (batch size: {BATCH_SIZE})"
    )

    for batch_idx, batch in enumerate(batches, 1):
        batch_json = json.dumps(batch, indent=2)
        prompt = _build_prompt(batch_json)

        logger.info(
            f"  Batch {batch_idx}/{len(batches)}: {len(batch)} blocks, "
            f"prompt {len(prompt)} chars"
        )

        try:
            response = await api_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=16384,
                messages=[{"role": "user", "content": prompt}],
            )

            logger.info(
                f"    Response: stop_reason={response.stop_reason}, "
                f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
            )

            # ── Safety: empty content check ──
            if not response.content or not response.content[0].text.strip():
                logger.warning(f"    Batch {batch_idx}: empty response, skipping")
                continue

            response_text = response.content[0].text.strip()

            # ── Truncation retry with 2x budget ──
            if response.stop_reason == "max_tokens":
                logger.warning(f"    Batch {batch_idx}: truncated, retrying with 2x budget...")
                try:
                    response = await api_client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=32768,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    if not response.content or not response.content[0].text.strip():
                        logger.warning(f"    Batch {batch_idx}: retry also empty, skipping")
                        continue
                    response_text = response.content[0].text.strip()
                    if response.stop_reason == "max_tokens":
                        logger.warning(f"    Batch {batch_idx}: still truncated after retry")
                except Exception as retry_err:
                    logger.warning(f"    Batch {batch_idx}: retry failed: {retry_err}")
                    # Fall through — try to parse whatever we got from the first attempt

            # ── Robust JSON extraction ──
            try:
                result = _extract_json_object(response_text)
            except ValueError:
                logger.warning(
                    f"    Batch {batch_idx}: JSON extraction failed, "
                    f"response text (first 300 chars): {response_text[:300]}"
                )
                continue

            # Filter out null values — only keep positively identified blocks
            batch_identified = 0
            for block_name, label in result.items():
                if label and isinstance(label, str) and len(label.strip()) > 1:
                    all_identified[block_name] = label.strip()
                    batch_identified += 1
                else:
                    total_null += 1

            logger.info(
                f"    Batch {batch_idx}: {batch_identified} identified, "
                f"{len(result) - batch_identified} null"
            )

        except Exception as e:
            logger.warning(
                f"    Batch {batch_idx} FAILED ({type(e).__name__}: {e}), "
                f"continuing with remaining batches..."
            )
            continue

    logger.info(
        f"  === CLASSIFICATION COMPLETE ===\n"
        f"  Total identified: {len(all_identified)}, total null: {total_null}\n"
        f"  ==========================="
    )
    if all_identified:
        for name, label in list(all_identified.items())[:20]:
            logger.info(f"    {name!r} → {label!r}")
        if len(all_identified) > 20:
            logger.info(f"    ... and {len(all_identified) - 20} more")

    return all_identified


def _build_system_prompt(drawing: ParseResponse, legend: LegendData | None = None) -> str:
    """Build a system prompt with the parsed drawing data injected."""
    symbol_data = []
    for s in drawing.symbols:
        entry = {
            "block_name": s.block_name,
            "label": s.label,
            "count": s.count,
        }
        if s.locations:
            entry["sample_locations"] = s.locations[:5]
        symbol_data.append(entry)

    data_json = json.dumps(symbol_data, indent=2)

    # Build legend context if available
    legend_section = ""
    if legend:
        legend_entries = "\n".join(
            f"  - {s.code}: {s.name} [{s.category}]"
            for s in legend.symbols
        )
        legend_section = f"""

PROJECT LEGEND (from "{legend.filename}"):
The contractor uploaded an official legend/key sheet for this project. The following symbols
are defined in the project's legend — use these as the authoritative reference:
{legend_entries}

When answering questions, reference the legend definitions. If a detected symbol matches
a legend entry, use the legend's official name and category.
"""

    return f"""You are FireGPT, a professional AI assistant built for fire alarm contractors \
and smart building engineers. You specialize in analyzing construction drawings, \
fire alarm system design, and project estimation.

You are helping a fire alarm contractor analyze a drawing file. Below is the extracted symbol data \
from the drawing "{drawing.filename}" ({drawing.file_type.upper()} format).
{legend_section}
EXTRACTED SYMBOL DATA:
{data_json}

TOTAL SYMBOLS DETECTED: {drawing.total_symbols}

INSTRUCTIONS:
- Answer questions about symbol counts, types, and locations accurately.
- When asked about counts, use the exact numbers from the data above.
- If asked about a symbol type not in the data, say it was not found in this drawing.
- "block_name" is the technical name from the CAD file. "label" is the human-readable name.
- Help with bid estimation, device scheduling, and material takeoffs.
- Be concise and direct. Fire alarm contractors need quick, accurate answers.
- If the user asks about something outside the drawing data, let them know you can only \
answer questions about the uploaded drawing.
- Format counts and lists clearly using markdown tables when appropriate.
- Use **bold** for important numbers and device names.

COST ESTIMATION GUIDELINES:
When asked about cost estimates, material pricing, or bid preparation, use these typical \
US market rates for fire alarm devices (2024-2025 pricing):

Detection Devices:
- Photoelectric Smoke Detector: $25-45 material + $75-120 labor per device
- Heat Detector (fixed/RoR): $20-35 material + $75-120 labor per device
- Duct Smoke Detector: $150-250 material + $200-350 labor per device
- Beam Detector: $300-600 material + $300-500 labor per device
- VESDA/Aspirating Detector: $1,500-5,000 material + $1,000-3,000 labor per unit
- Multi-sensor Detector: $50-80 material + $75-120 labor per device

Manual Devices:
- Pull Station: $30-50 material + $75-120 labor per device
- Break Glass Station: $35-55 material + $75-120 labor per device

Notification Appliances:
- Horn/Strobe: $40-80 material + $75-120 labor per device
- Horn only: $30-60 material + $75-100 labor per device
- Strobe only: $35-65 material + $75-100 labor per device
- Speaker (ceiling mount): $50-100 material + $100-150 labor per device
- Speaker (wall mount): $55-110 material + $100-150 labor per device
- Speaker/Strobe: $60-120 material + $100-150 labor per device
- Alarm Siren (indoor): $45-85 material + $75-120 labor per device
- Alarm Siren (outdoor/weatherproof): $65-130 material + $100-150 labor per device

System Components:
- Fire Alarm Control Panel (small): $2,000-5,000 material + $1,500-3,000 labor
- Fire Alarm Control Panel (large/networked): $5,000-15,000 material + $3,000-8,000 labor
- Annunciator Panel: $500-2,000 material + $500-1,500 labor
- Monitor Module: $35-60 material + $75-120 labor per module
- Control Module: $40-70 material + $75-120 labor per module
- Relay Module: $30-55 material + $75-100 labor per module

Infrastructure:
- Fire-rated wiring (FPLR/FPLP): $1.50-3.00 per linear foot
- Conduit (EMT): $3-8 per linear foot installed
- Average wire run per device: 50-100 feet
- Junction Box: $15-30 material + $40-60 labor
- Terminal Cabinet: $100-250 material + $100-200 labor
- Fire Door Holder/Release: $60-150 material + $100-200 labor

When providing estimates:
1. Present material costs and labor costs separately in a clear table
2. Always provide LOW and HIGH estimate ranges
3. Add 10-15% for project management, engineering, and overhead
4. Add 10-15% contingency for unforeseen conditions
5. Note that permits, engineering stamps, and inspection fees are additional
6. Mention that actual costs vary by region, project complexity, and market conditions
7. For wiring estimates, use average 75 feet per device unless the user specifies otherwise
8. Round totals to the nearest $100 for cleanliness"""


async def chat_with_drawing(
    message: str,
    drawing: ParseResponse,
    history: list[dict] | None = None,
    legend: LegendData | None = None,
) -> str:
    """Send a message to the LLM with drawing context and return the response."""
    api_client = _get_client()

    messages = []
    if history:
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    response = await api_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=_build_system_prompt(drawing, legend),
        messages=messages,
    )

    return response.content[0].text
