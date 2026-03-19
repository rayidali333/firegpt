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
    """Build the prompt for Claude to match symbols to legend entries."""

    return f"""You are an expert at matching fire alarm and MEP (Mechanical, Electrical, Plumbing) device names.

I have two lists:

1. DETECTED SYMBOLS from a DXF construction drawing — these have labels assigned by dictionary matching or AI classification:
{json.dumps(symbols, indent=2)}

2. LEGEND ENTRIES extracted from the project's symbol legend document — these are the official device names:
{json.dumps(legend_devices, indent=2)}

Your task: For each DETECTED SYMBOL, find the best matching LEGEND ENTRY based on:
- Name similarity (e.g., "Smoke Detector" in DXF ↔ "Smoke Detector" in legend)
- Abbreviation match (e.g., DXF block name contains "SD" ↔ legend abbreviation "SD")
- Category alignment (e.g., both are fire alarm devices)
- Semantic equivalence (e.g., "Horn/Strobe" ↔ "Wall Mounted Strobe Light 110CD")

RULES:
- Each detected symbol should match AT MOST one legend entry.
- A legend entry CAN match multiple detected symbols (e.g., different block variants of the same device).
- If no good match exists, use null. Do NOT force bad matches.
- Confidence levels: "high" (names nearly identical or abbreviation exact match), "medium" (semantic match but different wording), "low" (partial/uncertain match).
- Provide brief reasoning for each match to aid debugging.

Return ONLY valid JSON (no markdown fences):
{{
  "matches": [
    {{
      "symbol_label": "Smoke Detector",
      "legend_device_name": "Smoke Detector" or null,
      "confidence": "high" | "medium" | "low",
      "reasoning": "Brief explanation of why this match was chosen"
    }}
  ],
  "unmatched_legend_entries": ["Device Name 1", "Device Name 2"],
  "summary": "Brief summary of matching results"
}}"""


async def match_symbols_to_legend(
    symbols: list[SymbolInfo],
    legend_devices: list[LegendDevice],
    analysis: list[AnalysisStep],
) -> dict[str, LegendDevice | None]:
    """Match detected symbols to legend entries using AI.

    Args:
        symbols: Detected symbols from DXF parsing
        legend_devices: Extracted devices from legend
        analysis: Analysis log for debugging

    Returns:
        Dict mapping symbol label → matched LegendDevice (or None if unmatched)
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
            "label": s.label,
            "block_name": s.block_name,
            "count": s.count,
            "source": s.source,
        }
        if s.block_variants:
            summary["block_variants"] = s.block_variants
        symbol_summaries.append(summary)

    legend_summaries = []
    for d in legend_devices:
        summary: dict = {"name": d.name, "category": d.category}
        if d.abbreviation:
            summary["abbreviation"] = d.abbreviation
        legend_summaries.append(summary)

    _log(analysis, "info",
         f"Symbol labels: {', '.join(s.label for s in symbols)}")
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
    result: dict[str, LegendDevice | None] = {}
    matched_count = 0
    unmatched_count = 0
    confidence_counts = {"high": 0, "medium": 0, "low": 0}

    for match in matches_list:
        if not isinstance(match, dict):
            continue

        symbol_label = match.get("symbol_label", "")
        legend_name = match.get("legend_device_name")
        confidence = match.get("confidence", "low")
        reasoning = match.get("reasoning", "")

        if not symbol_label:
            continue

        if legend_name and legend_name in legend_by_name:
            device = legend_by_name[legend_name]
            result[symbol_label] = device
            matched_count += 1
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            _log(analysis, "success",
                 f"  ✓ \"{symbol_label}\" → \"{legend_name}\" "
                 f"[{confidence}] — {reasoning}")
        elif legend_name and legend_name.lower() in legend_by_name:
            # Case-insensitive fallback
            device = legend_by_name[legend_name.lower()]
            result[symbol_label] = device
            matched_count += 1
            confidence_counts[confidence] = confidence_counts.get(confidence, 0) + 1
            _log(analysis, "success",
                 f"  ✓ \"{symbol_label}\" → \"{device.name}\" "
                 f"[{confidence}, case-adjusted] — {reasoning}")
        else:
            result[symbol_label] = None
            unmatched_count += 1
            reason_str = f" — {reasoning}" if reasoning else ""
            _log(analysis, "warning" if legend_name else "info",
                 f"  ✗ \"{symbol_label}\" → no match"
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
