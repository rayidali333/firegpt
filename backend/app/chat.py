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

    prompt = """You are analyzing a construction drawing legend/key sheet. Extract EVERY symbol definition shown.

For each symbol, provide:
1. "code": The text code or abbreviation shown inside/next to the symbol (e.g., "MFACP", "CR", "SD", "DS", "ML"). If no code, use a short abbreviation of the name.
2. "name": The full device name exactly as written (e.g., "Main Fire Alarm Control Panel", "Proximity Card Reader")
3. "category": The system category it belongs to. Use EXACTLY one of these:
   - "Fire Alarm" — detectors, panels, modules, manual stations, sirens, strobes
   - "Access Control" — card readers, door locks, exit buttons, break glass
   - "Structured Cabling" — server racks, patch panels, data outlets
   - "BMS" — building management system panels, workstations, converters
   - "Video Surveillance" — CCTV cameras, workstations, NVR
   - "Public Address" — speakers, amplifiers, alarm racks
   - "Other" — anything that doesn't fit above
4. "shape": Describe the visual shape of the symbol (e.g., "circle with S inside", "square with MFACP text", "filled circle", "diamond")
5. "shape_code": Classify the marker shape as one of: "circle", "square", "diamond", "hexagon"
   - Circles/round shapes → "circle"
   - Squares/rectangles/boxes → "square"
   - Diamond/rotated squares → "diamond"
   - Hexagons or complex shapes → "hexagon"

Extract ALL symbols from ALL sections/systems shown in the legend. Do not skip any.

Respond with ONLY a JSON array:
[{"code": "MFACP", "name": "Main Fire Alarm Control Panel", "category": "Fire Alarm", "shape": "rectangle with MFACP text", "shape_code": "square"}, ...]"""

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
            symbols.append(LegendSymbol(
                code=entry.get("code", ""),
                name=entry.get("name", ""),
                category=entry.get("category", "Other"),
                shape=entry.get("shape", ""),
                shape_code=entry.get("shape_code", "circle"),
            ))
        except Exception as sym_err:
            logger.warning(f"Failed to parse symbol entry {i}: {entry} — {sym_err}")

    # Extract unique system categories
    systems = sorted(set(s.category for s in symbols))
    logger.info(
        f"Legend parsing complete: {len(symbols)} symbols across {len(systems)} systems: {systems}"
    )

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
        legend_entries = "\n".join(
            f'  - Code: "{s.code}" → {s.name} [{s.category}]'
            for s in legend.symbols
        )
        prompt = f"""You are a fire alarm and building systems expert analyzing a CAD construction drawing.

You have been provided with the OFFICIAL LEGEND/KEY for this project. Use it as the AUTHORITATIVE
source of truth to classify every block in the drawing.

PROJECT LEGEND (from "{legend.filename}"):
{legend_entries}

DRAWING CONTEXT:
{drawing_context}

BLOCKS TO CLASSIFY:
{blocks_json}

CLASSIFICATION GUIDELINES:
1. The legend above is the DEFINITIVE reference. Match blocks to legend entries by:
   - Block name containing the legend code (e.g., block "FA_MFACP_01" matches legend code "MFACP")
   - Text labels inside the block matching legend codes
   - Block attributes matching legend codes or names
   - Layer names suggesting the system category
2. Use the EXACT device name from the legend as the label (e.g., "Main Fire Alarm Control Panel")
3. Blocks from ALL systems in the legend should be classified (Fire Alarm, Access Control, BMS, CCTV, etc.)
4. Title blocks, sheet frames, borders, furniture, structural elements = null
5. When in doubt, classify as null. False negatives are better than false positives.
6. A block that appears hundreds of times and is NOT on any relevant system layer is likely NOT a device.

Respond with ONLY a JSON object. Identified devices get their legend name, everything else gets null:
{{"block_name_1": "Main Fire Alarm Control Panel", "block_name_2": null, ...}}"""
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
        response = await api_client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )

        response_text = response.content[0].text.strip()

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
        for block_name, label in result.items():
            if label and isinstance(label, str) and len(label.strip()) > 1:
                identified[block_name] = label.strip()

        return identified

    except json.JSONDecodeError:
        logger.warning("AI block classification returned invalid JSON")
        return {}
    except Exception as e:
        logger.warning(f"AI block classification failed: {e}")
        return {}


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
