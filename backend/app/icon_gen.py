"""
SVG Icon Generation — AI-powered creation of fire alarm device icons.

For each legend device with a symbol_description, this module sends the
description to Claude and receives back compact SVG markup. The icons
are cached in-memory by device name for reuse across drawings.

Icons are 24x24 viewBox, monochrome, and designed for use as inline
symbols in both the Symbol Table and Drawing View.
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
    """Build prompt for Claude to generate an SVG icon."""
    return f"""Generate a clean, minimal SVG icon for this fire alarm device symbol.

Device: {device_name}
Symbol description: {symbol_description}

Requirements:
- viewBox="0 0 24 24"
- Use only basic SVG elements: circle, rect, line, path, polygon, polyline, text, g
- Use stroke="#000" stroke-width="1.5" on all shape elements explicitly
- For filled areas, use fill="#000" explicitly on the element
- Keep it simple and recognizable at small sizes (16-24px)
- The icon should look like a technical/engineering symbol, not decorative art
- For detectors: use circles with internal markings
- For pull stations: use a rectangle with a T-handle
- For horns/strobes: use speaker/flash shapes
- For panels: use a rectangle with internal indicators
- For modules: use a small square with connection dots
- Do NOT include <?xml?> declaration, <!DOCTYPE>, or comments
- Do NOT include width/height attributes on the <svg> — only viewBox

Return ONLY the SVG markup starting with <svg and ending with </svg>. No explanation, no markdown fences."""


def _validate_svg(svg: str) -> str | None:
    """Validate and clean SVG markup. Returns cleaned SVG or None if invalid."""
    svg = svg.strip()

    # Extract SVG if wrapped in markdown fences
    if "```" in svg:
        match = re.search(r'<svg[\s\S]*</svg>', svg)
        if match:
            svg = match.group(0)
        else:
            return None

    # Must start with <svg and end with </svg>
    if not svg.startswith("<svg") or not svg.endswith("</svg>"):
        match = re.search(r'<svg[\s\S]*</svg>', svg)
        if match:
            svg = match.group(0)
        else:
            return None

    # Must have viewBox
    if "viewBox" not in svg:
        svg = svg.replace("<svg", '<svg viewBox="0 0 24 24"', 1)

    # Remove any width/height attributes (we control sizing via CSS)
    svg = re.sub(r'\s+width="[^"]*"', '', svg)
    svg = re.sub(r'\s+height="[^"]*"', '', svg)

    # Remove xmlns if present (not needed for inline SVG)
    svg = re.sub(r'\s+xmlns="[^"]*"', '', svg)

    return svg


async def generate_svg_icon(device_name: str, symbol_description: str) -> str | None:
    """Generate a single SVG icon for a device.

    Args:
        device_name: The legend device name
        symbol_description: Visual description from the legend

    Returns:
        SVG markup string, or None if generation failed
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
            f"(response length: {len(raw_svg)}, preview: {raw_svg[:200]})"
        )
        return None

    # Cache it
    icons_cache[device_name] = svg
    logger.info(
        f"[icon_gen] Generated icon for {device_name} "
        f"({len(svg)} bytes, {elapsed:.1f}s)"
    )
    return svg


async def generate_icons_batch(
    devices: list[dict],
) -> dict[str, str]:
    """Generate SVG icons for a batch of devices concurrently.

    Uses asyncio.Semaphore to limit concurrent API calls.

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
        logger.info(
            f"[icon_gen] All {cached} icons served from cache"
        )
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
