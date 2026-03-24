"""
Symbol-to-Legend Matching — AI-powered linking of detected DXF symbols
to their corresponding legend entries.

When a user has both a parsed drawing (with detected symbols) and a parsed
legend (with device names, abbreviations, descriptions), this module uses
Claude to match each detected symbol to the most likely legend entry.

This enables:
1. Enriching detected symbols with detailed legend descriptions
2. Generating accurate SVG icons from those descriptions (Phase 2)
3. Replacing colored circle markers with real device icons (Phase 3)
"""

import json
import logging
import os
import time

from anthropic import AsyncAnthropic

from app.models import AnalysisStep, LegendDevice, SymbolInfo

logger = logging.getLogger(__name__)

# Use Sonnet for matching — it's a structured mapping task, not vision.
# Opus would be overkill and slower here.
MATCHING_MODEL = "claude-sonnet-4-20250514"
MATCHING_MAX_TOKENS = 8192
MATCHING_TEMPERATURE = 0.1  # Very low for deterministic matching

client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = AsyncAnthropic(api_key=api_key)
    return client


def _log(analysis: list[AnalysisStep], type: str, message: str):
    """Append an analysis step and log it."""
    analysis.append(AnalysisStep(type=type, message=message))
    log_fn = {"info": logger.info, "success": logger.info,
              "warning": logger.warning, "error": logger.error}.get(
        type, logger.info)
    log_fn(f"[matching] {message}")


def _build_matching_prompt(
    symbols: list[dict],
    legend_devices: list[dict],
) -> str:
    """Build the prompt for Claude to match raw DXF block names to legend entries."""

    return f"""You are an expert at matching CAD block names from construction drawings to their corresponding legend/symbol key entries.

I have two lists:

1. RAW BLOCK NAMES from a DXF construction drawing — these are the internal CAD block names (not human-readable labels). They may use abbreviations, project-specific codes, or cryptic naming conventions:
{json.dumps(symbols, indent=2)}

2. LEGEND ENTRIES extracted from the project's symbol legend document — these are the official device names with abbreviations and categories:
{json.dumps(legend_devices, indent=2)}

Your task: For each RAW BLOCK, find the best matching LEGEND ENTRY based on:
- Abbreviation match (e.g., block name contains "SD" or "SMKDET" ↔ legend abbreviation "SD" for "Smoke Detector")
- Keyword overlap (e.g., block name "FA_HORN_STROBE_WALL" contains "HORN" and "STROBE" ↔ legend entry "Horn/Strobe")
- Common CAD naming patterns (e.g., prefixes like "FA_", "MEP_", suffixes like "_2D", "_SYM" should be ignored)
- Category alignment (e.g., fire alarm, electrical, plumbing — match within the same system)
- Count as a hint — high-count blocks are more likely to be commonly-placed devices

RULES:
- Each block should match AT MOST one legend entry.
- A legend entry CAN match multiple blocks (e.g., "SD-1" and "SMKDET_TYPE2" both → "Smoke Detector").
- If no good match exists, use null. Do NOT force bad matches — unmatched blocks are fine.
- Many blocks will be structural/architectural elements (walls, doors, furniture, titleblocks) that have NO legend match — leave these as null.
- Confidence levels: "high" (abbreviation exact match or very clear keyword match), "medium" (partial keyword or semantic match), "low" (uncertain/weak match).
- Provide brief reasoning for each match.

Return ONLY valid JSON (no markdown fences):
{{
  "matches": [
    {{
      "block_name": "FA_SD_CEILING",
      "legend_device_name": "Smoke Detector" or null,
      "confidence": "high" | "medium" | "low",
      "reasoning": "Brief explanation of why this match was chosen"
    }}
  ],
  "unmatched_legend_entries": ["Device Name 1", "Device Name 2"],
  "summary": "Brief summary of matching results"
}}"""


class MatchResult:
    """Result of matching a single symbol to a legend entry."""
    __slots__ = ("device", "confidence", "reasoning")

    def __init__(self, device: LegendDevice | None, confidence: str, reasoning: str = ""):
        self.device = device
        self.confidence = confidence  # "high" | "medium" | "low"
        self.reasoning = reasoning


async def match_symbols_to_legend(
    symbols: list[SymbolInfo],
    legend_devices: list[LegendDevice],
    analysis: list[AnalysisStep],
) -> dict[str, MatchResult]:
    """Match raw DXF block names to legend entries using AI.

    Args:
        symbols: Raw symbols from DXF parsing (block_name as label)
        legend_devices: Extracted devices from legend
        analysis: Analysis log for debugging

    Returns:
        Dict mapping block_name → MatchResult (with device, confidence, reasoning)
    """
    _log(analysis, "info",
         "━━━ Legend Matching ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

    if not symbols:
        _log(analysis, "warning", "No symbols to match — drawing has no detected symbols")
        return {}

    if not legend_devices:
        _log(analysis, "warning", "No legend devices to match against — legend is empty")
        return {}

    _log(analysis, "info",
         f"Matching {len(symbols)} detected symbols against "
         f"{len(legend_devices)} legend entries")

    # Build simplified lists for the prompt (strip large data like locations)
    symbol_summaries = []
    for s in symbols:
        summary = {
            "block_name": s.block_name,
            "count": s.count,
        }
        symbol_summaries.append(summary)

    legend_summaries = []
    for d in legend_devices:
        summary: dict = {"name": d.name, "category": d.category}
        if d.abbreviation:
            summary["abbreviation"] = d.abbreviation
        legend_summaries.append(summary)

    _log(analysis, "info",
         f"Block names: {', '.join(s.block_name for s in symbols[:20])}"
         + (f" (+{len(symbols) - 20} more)" if len(symbols) > 20 else ""))
    _log(analysis, "info",
         f"Legend devices: {', '.join(d.name for d in legend_devices[:20])}"
         + (f" (+{len(legend_devices) - 20} more)" if len(legend_devices) > 20 else ""))

    # Call Claude
    prompt = _build_matching_prompt(symbol_summaries, legend_summaries)
    api_client = _get_client()

    start_time = time.time()
    try:
        response = await api_client.messages.create(
            model=MATCHING_MODEL,
            max_tokens=MATCHING_MAX_TOKENS,
            temperature=MATCHING_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        _log(analysis, "error", f"Claude API call failed: {e}")
        raise

    elapsed = time.time() - start_time
    response_text = response.content[0].text.strip()

    usage = response.usage
    _log(analysis, "info",
         f"Claude responded in {elapsed:.1f}s "
         f"({usage.input_tokens} input, {usage.output_tokens} output tokens)")

    # Parse response
    try:
        data = json.loads(_extract_json(response_text))
    except json.JSONDecodeError as e:
        _log(analysis, "error", f"Failed to parse matching response as JSON: {e}")
        _log(analysis, "info", f"Response preview: {response_text[:500]}")
        return {}

    matches_list = data.get("matches", [])
    if not isinstance(matches_list, list):
        _log(analysis, "error", "Invalid response: 'matches' is not a list")
        return {}

    # Build a lookup for legend devices by name
    legend_by_name: dict[str, LegendDevice] = {}
    for d in legend_devices:
        legend_by_name[d.name] = d
        # Also index by lowercase for case-insensitive fallback
        legend_by_name[d.name.lower()] = d

    # Process matches
    result: dict[str, MatchResult] = {}
    matched_count = 0
    unmatched_count = 0
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

    for match in matches_list:
        if not isinstance(match, dict):
            continue

        block_name = match.get("block_name", "")
        legend_name = match.get("legend_device_name")
        confidence = match.get("confidence", "low")
        reasoning = match.get("reasoning", "")

        if not block_name:
            continue

        if legend_name and legend_name in legend_by_name:
            device = legend_by_name[legend_name]
            result[block_name] = MatchResult(device, confidence, reasoning)
            matched_count += 1
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            _log(analysis, "success",
                 f"  ✓ \"{block_name}\" → \"{legend_name}\" "
                 f"[{confidence}] — {reasoning}")
        elif legend_name and legend_name.lower() in legend_by_name:
            # Case-insensitive fallback
            device = legend_by_name[legend_name.lower()]
            result[block_name] = MatchResult(device, confidence, reasoning)
            matched_count += 1
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            _log(analysis, "success",
                 f"  ✓ \"{block_name}\" → \"{device.name}\" "
                 f"[{confidence}, case-adjusted] — {reasoning}")
        else:
            result[block_name] = MatchResult(None, "low", reasoning)
            unmatched_count += 1
            reason_str = f" — {reasoning}" if reasoning else ""
            _log(analysis, "info",
                 f"  ✗ \"{block_name}\" → no match"
                 f"{reason_str}")

    # Log unmatched legend entries
    unmatched_legend = data.get("unmatched_legend_entries", [])
    if unmatched_legend:
        _log(analysis, "info",
             f"Legend entries not matched to any detected symbol ({len(unmatched_legend)}): "
             + ", ".join(f'"{n}"' for n in unmatched_legend[:15])
             + (f" (+{len(unmatched_legend) - 15} more)" if len(unmatched_legend) > 15 else ""))

    # Summary
    summary = data.get("summary", "")
    conf_str = ", ".join(f"{k}: {v}" for k, v in confidence_counts.items() if v > 0)
    _log(analysis, "success",
         f"Matching complete: {matched_count} matched, "
         f"{unmatched_count} unmatched ({conf_str})")
    if summary:
        _log(analysis, "info", f"AI summary: {summary}")

    return result


def _extract_json(text: str) -> str:
    """Extract JSON from a response that might have markdown fences."""
    text = text.strip()
    if text.startswith("{"):
        return text

    # Try markdown code fences
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        return text[start:end].strip()

    if "```" in text:
        start = text.index("```") + 3
        end = text.index("```", start)
        return text[start:end].strip()

    # Try to find the first { and last }
    first_brace = text.find("{")
    last_brace = text.rfind("}")
    if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
        return text[first_brace:last_brace + 1]

    return text
