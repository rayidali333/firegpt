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


async def parse_legend_with_vision(
    image_data: bytes,
    media_type: str,
    filename: str,
) -> LegendData:
    """Use Claude Vision to parse a legend sheet image/PDF into structured symbol data.

    Sends the legend image to Claude and extracts all symbol definitions with their
    codes, names, categories, and visual shapes.
    """
    import base64
    import uuid

    logger.info("=== parse_legend_with_vision START ===")
    logger.info(f"Filename: {filename}, media_type: {media_type}, data_size: {len(image_data)} bytes")

    api_client = _get_client()
    logger.info("Anthropic client initialized successfully")

    image_b64 = base64.standard_b64encode(image_data).decode("utf-8")
    logger.info(f"Base64 encoded size: {len(image_b64)} chars")

    prompt = """You are analyzing a construction drawing legend/key sheet. Extract EVERY symbol that is PHYSICALLY SHOWN as a distinct row in the legend.

CRITICAL ANTI-HALLUCINATION RULES:
- ONLY extract symbols that are ACTUALLY VISIBLE as distinct rows in the legend image.
- Each legend row has TWO parts: (1) a graphic symbol on the left, (2) a text description on the right.
- You MUST be able to point to BOTH the symbol graphic AND the adjacent description text for every entry.
- Do NOT invent symbols based on what you think "should" be in the legend.
- Do NOT decompose a description into sub-devices (e.g., "Addressable Input Module Connected to Flow Switch" is ONE entry — do NOT create a separate "Flow Switch" entry unless there is a distinct row for it).
- Do NOT add devices from general industry knowledge — ONLY what is physically drawn and labeled in this image.
- "Weatherproof" variants ARE separate entries IF they have their own distinct row with their own symbol graphic.

WHAT COUNTS AS A VALID LEGEND ENTRY:
✓ A row with a symbol shape (rectangle, hexagon, circle, etc.) and text description next to it
✓ A row with a graphical icon (like a line symbol for cable) and text description next to it
✗ A device name mentioned only within another entry's description
✗ A device you know exists in fire alarm systems but isn't drawn in this legend
✗ A sub-component extracted from a longer description

For each visible symbol row, provide:
1. "code": The EXACT text shown INSIDE the symbol shape. Read character by character.
   - Text codes like "MFACP", "SCM", "S", "H", "CR", "DS" — use EXACTLY what you read.
   - For subscripts: "S" with subscript "WP" → "SWP", "S" with subscript "80" → "S80"
   - If the symbol has NO text inside (purely graphical), describe what you see briefly, e.g., "graphic_beam_tx" for a beam transmitter icon. Use lowercase with underscores.
2. "name": The full device name EXACTLY as written next to the symbol. Copy the text verbatim — do NOT rephrase.
3. "category": The section header this row falls under. Use EXACTLY one of:
   - "Fire Alarm", "Access Control", "Structured Cabling", "BMS", "Video Surveillance", "Public Address", "Other"
4. "shape": Describe the visual shape precisely. Count sides carefully:
   - 6 sides = hexagon (VERY COMMON for detectors)
   - 5 sides = pentagon
   - 4 sides = square/rectangle
   - 3 sides = triangle
   - Round = circle
5. "shape_code": "circle", "square", "diamond", "pentagon", "hexagon", "triangle", or "star"
6. "filled": true if the shape is filled/solid, false if outline only

SHAPE GUIDANCE:
- Fire alarm DETECTORS almost always use HEXAGONS. Count carefully!
- Panels and modules → "square"
- If unsure between pentagon and hexagon → almost certainly HEXAGON

Respond with ONLY a JSON array:
[{"code": "S", "name": "Smoke Detector", "category": "Fire Alarm", "shape": "hexagon with S inside", "shape_code": "hexagon", "filled": false}, ...]"""

    # PDFs use "document" content type; images use "image" content type
    if media_type == "application/pdf":
        file_content_block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64,
            },
        }
    else:
        file_content_block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64,
            },
        }

    logger.info(f"Sending {media_type} to Claude API (model: claude-sonnet-4-20250514, max_tokens: 16384)...")
    try:
        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[{
                "role": "user",
                "content": [
                    file_content_block,
                    {
                        "type": "text",
                        "text": prompt,
                    },
                ],
            }],
        )
    except Exception as api_err:
        logger.error(f"Claude API call failed: {type(api_err).__name__}: {api_err}")
        raise

    logger.info(
        f"Claude API response received: stop_reason={response.stop_reason}, "
        f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
    )

    if response.stop_reason == "max_tokens":
        logger.warning(
            "Legend parsing response was TRUNCATED (hit max_tokens). "
            "Some symbols may be missing."
        )

    if not response.content:
        logger.error("Claude returned empty content array")
        raise ValueError("Claude returned no content in response")

    response_text = response.content[0].text.strip()
    logger.info(f"Response text length: {len(response_text)} chars")
    logger.debug(f"Response text (first 500 chars): {response_text[:500]}")

    # Extract JSON array from response, handling various LLM output formats
    try:
        raw_symbols = _extract_json_array(response_text)
    except (ValueError, json.JSONDecodeError) as parse_err:
        logger.error(f"JSON extraction failed: {parse_err}")
        logger.error(f"Full response text:\n{response_text}")
        raise

    logger.info(f"Extracted {len(raw_symbols)} raw symbol entries from AI response")

    symbols = []
    for i, entry in enumerate(raw_symbols):
        try:
            sym = LegendSymbol(
                code=entry.get("code", ""),
                name=entry.get("name", ""),
                category=entry.get("category", "Other"),
                shape=entry.get("shape", ""),
                shape_code=entry.get("shape_code", "circle"),
                filled=bool(entry.get("filled", False)),
            )
            # Apply domain-knowledge shape correction
            sym = _correct_legend_shape(sym)
            symbols.append(sym)
        except Exception as sym_err:
            logger.warning(f"Failed to parse symbol entry {i}: {entry} — {sym_err}")

    # === VALIDATION PASS ===
    # Instead of asking "what did I miss?" (which encourages hallucination),
    # ask "which of these are actually in the image?" (which encourages pruning).
    logger.info(f"Pass 1 extracted {len(symbols)} symbols. Running validation pass to remove hallucinations...")
    try:
        existing_summary = "\n".join(
            f'  {i+1}. [{s.category}] code="{s.code}" — "{s.name}"'
            for i, s in enumerate(symbols)
        )
        validate_prompt = f"""I extracted {len(symbols)} symbols from this construction drawing legend. But I may have HALLUCINATED some entries — inventing devices that aren't actually shown in the legend image.

HERE IS MY LIST:
{existing_summary}

YOUR TASK: Look at the legend image VERY CAREFULLY. For each entry in my list, determine:
- Is there ACTUALLY a distinct row in the legend with a symbol graphic and this description?
- Or did I fabricate this entry based on general knowledge?

HALLUCINATION RED FLAGS:
- An entry whose name does not appear as text next to a symbol in the legend
- An entry that was extracted from within another entry's description (e.g., "Flow Switch" extracted from "Input Module Connected to Flow Switch")
- An entry for a device that exists in the industry but is not shown in THIS specific legend
- An entry where the code is a descriptive word I made up (like "interface", "flow_switch") rather than actual text visible inside a symbol shape

Return a JSON array containing ONLY the INDEX NUMBERS (1-based) of entries that are HALLUCINATED (not actually in the legend).
Example: [3, 7, 15, 22] means entries 3, 7, 15, and 22 should be removed.
If all entries are valid, return: []

Respond with ONLY the JSON array of indices to remove."""

        validate_response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{
                "role": "user",
                "content": [
                    file_content_block,
                    {"type": "text", "text": validate_prompt},
                ],
            }],
        )

        logger.info(
            f"Validation pass response: stop_reason={validate_response.stop_reason}, "
            f"usage={{input: {validate_response.usage.input_tokens}, output: {validate_response.usage.output_tokens}}}"
        )

        validate_text = validate_response.content[0].text.strip()
        indices_to_remove = _extract_json_array(validate_text)

        if indices_to_remove and isinstance(indices_to_remove, list):
            # Convert 1-based indices to 0-based, validate they're integers
            remove_set = set()
            for idx in indices_to_remove:
                if isinstance(idx, (int, float)):
                    remove_set.add(int(idx) - 1)  # Convert to 0-based

            if remove_set:
                removed_names = [
                    f'"{symbols[i].code}" ({symbols[i].name})'
                    for i in sorted(remove_set) if 0 <= i < len(symbols)
                ]
                symbols = [s for i, s in enumerate(symbols) if i not in remove_set]
                logger.info(
                    f"Validation pass removed {len(remove_set)} hallucinated entries: "
                    f"{', '.join(removed_names[:10])}"
                    f"{'...' if len(removed_names) > 10 else ''}"
                    f". Remaining: {len(symbols)} symbols"
                )
            else:
                logger.info("Validation pass: no hallucinated entries found")
        else:
            logger.info("Validation pass: all entries confirmed as valid")

    except Exception as validate_err:
        logger.warning(f"Validation pass failed (non-fatal): {type(validate_err).__name__}: {validate_err}")

    # Extract unique system categories
    systems = sorted(set(s.category for s in symbols))
    logger.info(
        f"Legend parsing complete: {len(symbols)} symbols across {len(systems)} systems: {systems}"
    )

    # Generate SVG icons for each symbol (second AI layer)
    try:
        symbols = await _generate_symbol_svgs(symbols)
    except Exception as svg_err:
        logger.warning(f"SVG icon generation failed entirely (non-fatal): {svg_err}")

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

    # Build structured metadata for each candidate block
    blocks_data = []
    for block in ai_candidate_blocks:
        entry = {
            "block_name": block.block_name,
            "count": block.count,
            "layers": block.layers,
        }
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

    blocks_json = json.dumps(blocks_data, indent=2)

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

    # Build prompt — legend-aware or standard
    if legend:
        # Legend-aware prompt: use legend as authoritative source
        # Build a numbered list of valid labels so the AI MUST pick from this exact set
        valid_labels = []
        legend_entries_lines = []
        for idx, s in enumerate(legend.symbols):
            valid_labels.append(s.name)
            legend_entries_lines.append(
                f'  {idx+1}. Code: "{s.code}" → "{s.name}" [{s.category}]'
            )
        legend_entries = "\n".join(legend_entries_lines)

        # Build a JSON-style list of the exact valid label strings
        valid_labels_json = json.dumps(valid_labels)

        prompt = f"""You are a fire alarm and building systems expert analyzing a CAD construction drawing.

You have been provided with the OFFICIAL LEGEND/KEY for this project. Use it as the AUTHORITATIVE
source of truth to classify every block in the drawing.

PROJECT LEGEND (from "{legend.filename}"):
{legend_entries}

DRAWING CONTEXT:
{drawing_context}

BLOCKS TO CLASSIFY:
{blocks_json}

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
        # Standard prompt — no legend available
        prompt = f"""You are a fire alarm systems expert analyzing a CAD construction drawing.

Your job: classify each unidentified block as either a fire alarm / building safety device,
or as NOT a fire alarm device (furniture, plumbing, structural, annotation, etc.).

DRAWING CONTEXT:
{drawing_context}

BLOCKS TO CLASSIFY:
{blocks_json}

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

    try:
        api_client = _get_client()

        logger.info(
            f"=== AI BLOCK CLASSIFICATION START ===\n"
            f"  Blocks to classify: {len(ai_candidate_blocks)}\n"
            f"  Legend: {'yes (' + str(len(legend.symbols)) + ' symbols)' if legend else 'no'}\n"
            f"  Prompt length: {len(prompt)} chars"
        )

        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=16384,
            messages=[{"role": "user", "content": prompt}],
        )

        logger.info(
            f"  Claude response: stop_reason={response.stop_reason}, "
            f"usage={{input: {response.usage.input_tokens}, output: {response.usage.output_tokens}}}"
        )

        if response.stop_reason == "max_tokens":
            logger.warning("AI classification response was TRUNCATED (hit max_tokens)")

        response_text = response.content[0].text.strip()
        logger.debug(f"  Response text (first 500 chars): {response_text[:500]}")

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

        # Filter out null values — only return positively identified blocks
        identified = {}
        null_count = 0
        for block_name, label in result.items():
            if label and isinstance(label, str) and len(label.strip()) > 1:
                identified[block_name] = label.strip()
            else:
                null_count += 1

        logger.info(
            f"  Classification result: {len(identified)} identified, {null_count} null/skipped\n"
            f"  ==========================="
        )
        if identified:
            for name, label in list(identified.items())[:20]:
                logger.info(f"    {name!r} → {label!r}")
            if len(identified) > 20:
                logger.info(f"    ... and {len(identified) - 20} more")

        return identified

    except json.JSONDecodeError as e:
        logger.error(f"AI block classification returned invalid JSON: {e}")
        logger.error(f"Response text:\n{response_text[:1000]}")
        raise  # Re-raise so caller can surface in analysis log
    except Exception as e:
        logger.error(f"AI block classification failed: {type(e).__name__}: {e}")
        raise  # Re-raise so caller can surface in analysis log


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
