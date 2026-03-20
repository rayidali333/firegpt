"""
SVG Icon Generation — AI-powered creation of fire alarm device icons.

Each icon is generated from the legend's symbol_description, so icons
accurately reflect the actual symbols used in each specific project.
Post-processing normalizes all colors to currentColor for automatic
CSS-driven per-category color coding.

Icons are 24×24 viewBox, designed for 18-22px inline rendering.
"""

import asyncio
import logging
import os
import re
import time

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

ICON_MODEL = "claude-sonnet-4-20250514"
ICON_MAX_TOKENS = 2048
ICON_TEMPERATURE = 0.2

# Max concurrent API calls to avoid rate limiting
MAX_CONCURRENT = 5

# In-memory cache: device name → SVG string
icons_cache: dict[str, str] = {}

client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        client = AsyncAnthropic(api_key=api_key)
    return client


def _build_icon_prompt(device_name: str, symbol_description: str) -> str:
    """Build prompt for Claude to generate an SVG icon.

    Uses explicit #000 for strokes/fills (Claude generates clearer icons
    with concrete color values). Post-processing in _normalize_colors()
    converts #000 → currentColor for CSS-driven per-category coloring.
    """
    return f"""Generate a clean, minimal SVG icon for this fire alarm device symbol.

Device: {device_name}
Symbol description: {symbol_description}

Requirements:
- viewBox="0 0 24 24"
- Use only basic SVG elements: circle, rect, line, path, polygon, polyline, text, g
- Use stroke="#000" stroke-width="1.5" explicitly on ALL shape elements
- For filled areas, use fill="#000" explicitly on the element
- For shape backgrounds/outlines, use fill="none" or fill="white"
- Keep it simple and recognizable at small sizes (16-24px)
- The icon should look like a technical/engineering symbol, not decorative art
- Center all content — main shape should fill ~80% of the 24×24 viewBox
- Use 3-8 SVG elements maximum

Text/letter rules (if the symbol contains a letter or abbreviation):
- Use <text> with font-size="11" font-weight="bold" font-family="Arial, sans-serif"
- Center text: text-anchor="middle" dominant-baseline="central" x="12" y="12"
- Make text PROMINENT — it should be the most visible element
- Text fill="#000" (no stroke on text elements)

Device type guidance:
- For detectors (smoke, heat, duct): use circles with internal markings or letters
- For pull stations: use a rectangle with a T-handle shape
- For horns/strobes/speakers: use speaker cone or flash/burst shapes
- For control panels: use a rectangle with internal indicator elements
- For modules/relays: use a small square or diamond with connection dots
- For sprinklers: use a circle with spray lines below

Do NOT include <?xml?> declaration, <!DOCTYPE>, comments, width, height, or xmlns attributes.

Return ONLY the SVG markup starting with <svg and ending with </svg>. No explanation, no markdown fences."""


def _normalize_colors(svg: str) -> str:
    """Replace all hardcoded colors with currentColor for CSS-driven coloring.

    Preserves fill="none", fill="white", fill="transparent" and their stroke
    equivalents. Everything else becomes currentColor so the parent element's
    CSS `color` property controls the icon color.
    """
    # Replace stroke colors (except none/currentColor)
    svg = re.sub(
        r'stroke="(?!currentColor|none)[^"]*"',
        'stroke="currentColor"',
        svg,
    )
    # Replace fill colors (except none/white/currentColor/transparent)
    svg = re.sub(
        r'fill="(?!currentColor|none|white|transparent|#fff|#FFF|#ffffff|#FFFFFF)[^"]*"',
        'fill="currentColor"',
        svg,
    )
    return svg


def _validate_svg(svg: str) -> str | None:
    """Validate, clean, and normalize SVG markup.

    Returns cleaned SVG with currentColor normalization, or None if invalid.
    """
    svg = svg.strip()

    # Extract SVG if wrapped in markdown fences
    if "```" in svg:
        match = re.search(r'<svg[\s\S]*</svg>', svg)
        if match:
            svg = match.group(0)
        else:
            return None

    # Must contain <svg and </svg>
    if not svg.startswith("<svg") or not svg.endswith("</svg>"):
        match = re.search(r'<svg[\s\S]*</svg>', svg)
        if match:
            svg = match.group(0)
        else:
            return None

    # Ensure viewBox
    if "viewBox" not in svg:
        svg = svg.replace("<svg", '<svg viewBox="0 0 24 24"', 1)

    # Remove width/height (we control sizing via CSS)
    svg = re.sub(r'\s+width="[^"]*"', '', svg)
    svg = re.sub(r'\s+height="[^"]*"', '', svg)

    # Remove xmlns (not needed for inline SVG)
    svg = re.sub(r'\s+xmlns="[^"]*"', '', svg)

    # Normalize all colors to currentColor
    svg = _normalize_colors(svg)

    return svg


async def generate_svg_icon(device_name: str, symbol_description: str) -> str | None:
    """Generate a single SVG icon from a device's symbol description.

    Args:
        device_name: Device name from the legend
        symbol_description: Visual description of the symbol from the legend

    Returns:
        SVG markup string with currentColor, or None if generation failed
    """
    # Check cache first
    if device_name in icons_cache:
        logger.info(f"[icon_gen] Cache hit: {device_name}")
        return icons_cache[device_name]

    prompt = _build_icon_prompt(device_name, symbol_description)
    api_client = _get_client()

    start_time = time.time()
    try:
        response = await api_client.messages.create(
            model=ICON_MODEL,
            max_tokens=ICON_MAX_TOKENS,
            temperature=ICON_TEMPERATURE,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as e:
        logger.error(f"[icon_gen] API call failed for {device_name}: {e}")
        return None

    elapsed = time.time() - start_time
    raw_svg = response.content[0].text.strip()

    svg = _validate_svg(raw_svg)
    if svg is None:
        logger.warning(
            f"[icon_gen] Invalid SVG for {device_name} "
            f"(len={len(raw_svg)}, preview={raw_svg[:200]})"
        )
        return None

    # Cache it
    icons_cache[device_name] = svg
    logger.info(
        f"[icon_gen] Generated icon for {device_name} "
        f"({len(svg)}B, {elapsed:.1f}s)"
    )
    return svg


async def generate_icons_batch(
    devices: list[dict],
) -> dict[str, str]:
    """Generate SVG icons for a batch of devices concurrently.

    Uses asyncio.Semaphore to limit concurrent API calls to MAX_CONCURRENT.

    Args:
        devices: List of dicts with 'name' and 'symbol_description' keys

    Returns:
        Dict mapping device name → SVG string (only successful generations)
    """
    results: dict[str, str] = {}
    to_generate: list[dict] = []

    # Resolve cache hits first
    for device in devices:
        name = device["name"]
        if name in icons_cache:
            results[name] = icons_cache[name]
        else:
            to_generate.append(device)

    cached = len(results)
    if not to_generate:
        logger.info(f"[icon_gen] All {cached} icons served from cache")
        return results

    start_time = time.time()
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _gen(device: dict) -> tuple[str, str | None]:
        async with sem:
            svg = await generate_svg_icon(
                device["name"], device["symbol_description"]
            )
            return device["name"], svg

    # Run all API calls concurrently (bounded by semaphore)
    tasks = [_gen(d) for d in to_generate]
    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    generated = 0
    failed = 0
    for outcome in outcomes:
        if isinstance(outcome, Exception):
            logger.error(f"[icon_gen] Task exception: {outcome}")
            failed += 1
        else:
            name, svg = outcome
            if svg:
                results[name] = svg
                generated += 1
            else:
                failed += 1

    elapsed = time.time() - start_time
    logger.info(
        f"[icon_gen] Batch complete: {generated} generated, "
        f"{cached} cached, {failed} failed out of {len(devices)} "
        f"({elapsed:.1f}s total)"
    )

    return results
