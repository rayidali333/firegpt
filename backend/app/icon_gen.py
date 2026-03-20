"""
SVG Icon Generation — deterministic templates for fire alarm device icons.

Instead of AI-generated SVGs (which are inconsistent), this module uses
handcrafted SVG templates mapped to device types via keyword matching.
All icons use currentColor for strokes/fills, so they inherit color from
the CSS container — giving automatic per-category color coding.

Icons are 24×24 viewBox, designed for 18-22px rendering.
"""

import logging

logger = logging.getLogger(__name__)

# In-memory cache: device name → SVG string
icons_cache: dict[str, str] = {}


# ── SVG Templates ─────────────────────────────────────────────────────
# All use currentColor so color is controlled by CSS parent.


def _circle_icon(letter: str) -> str:
    """Circle with centered letter(s) — for detectors."""
    fs = 12 if len(letter) == 1 else (9 if len(letter) == 2 else 7)
    return (
        '<svg viewBox="0 0 24 24">'
        '<circle cx="12" cy="12" r="10" stroke="currentColor" '
        'stroke-width="1.5" fill="white"/>'
        f'<text x="12" y="12" text-anchor="middle" dy="0.38em" '
        f'font-size="{fs}" font-family="Arial,sans-serif" '
        f'font-weight="bold" fill="currentColor">{letter}</text>'
        '</svg>'
    )


def _rect_icon(letter: str) -> str:
    """Rounded rectangle with centered letter(s) — for modules."""
    fs = 10 if len(letter) <= 2 else 7
    return (
        '<svg viewBox="0 0 24 24">'
        '<rect x="2" y="4" width="20" height="16" rx="2" '
        'stroke="currentColor" stroke-width="1.5" fill="white"/>'
        f'<text x="12" y="12" text-anchor="middle" dy="0.38em" '
        f'font-size="{fs}" font-family="Arial,sans-serif" '
        f'font-weight="bold" fill="currentColor">{letter}</text>'
        '</svg>'
    )


def _panel_icon(letter: str = "FP") -> str:
    """Control panel — rectangle with header bar and letters."""
    fs = 9 if len(letter) <= 2 else 7
    return (
        '<svg viewBox="0 0 24 24">'
        '<rect x="2" y="3" width="20" height="18" rx="2" '
        'stroke="currentColor" stroke-width="1.5" fill="white"/>'
        '<line x1="2" y1="8" x2="22" y2="8" '
        'stroke="currentColor" stroke-width="1" opacity="0.4"/>'
        f'<text x="12" y="14" text-anchor="middle" dy="0.38em" '
        f'font-size="{fs}" font-family="Arial,sans-serif" '
        f'font-weight="bold" fill="currentColor">{letter}</text>'
        '</svg>'
    )


def _diamond_icon(letter: str = "") -> str:
    """Diamond shape — for switches, valves."""
    inner = ""
    if letter:
        fs = 9 if len(letter) <= 2 else 7
        inner = (
            f'<text x="12" y="12" text-anchor="middle" dy="0.38em" '
            f'font-size="{fs}" font-family="Arial,sans-serif" '
            f'font-weight="bold" fill="currentColor">{letter}</text>'
        )
    return (
        '<svg viewBox="0 0 24 24">'
        '<polygon points="12,2 22,12 12,22 2,12" '
        'stroke="currentColor" stroke-width="1.5" fill="white" '
        'stroke-linejoin="round"/>'
        + inner +
        '</svg>'
    )


def _speaker_icon() -> str:
    """Speaker/loudspeaker icon."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<polygon points="3,9 3,15 7,15 13,19 13,5 7,9" '
        'stroke="currentColor" stroke-width="1.5" fill="white" '
        'stroke-linejoin="round"/>'
        '<path d="M16,9 Q19.5,12 16,15" stroke="currentColor" '
        'stroke-width="1.5" fill="none"/>'
        '<path d="M18.5,7 Q23,12 18.5,17" stroke="currentColor" '
        'stroke-width="1.5" fill="none"/>'
        '</svg>'
    )


def _strobe_icon() -> str:
    """Strobe/flash light icon — circle with lightning bolt."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<circle cx="12" cy="12" r="10" stroke="currentColor" '
        'stroke-width="1.5" fill="white"/>'
        '<path d="M14,4.5 L9.5,12 L13,12 L10,19.5" '
        'stroke="currentColor" stroke-width="2" fill="none" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )


def _horn_icon() -> str:
    """Horn/audible notification."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<path d="M4,9 L4,15 L8,15 L15,19 L15,5 L8,9 Z" '
        'stroke="currentColor" stroke-width="1.5" fill="white" '
        'stroke-linejoin="round"/>'
        '<line x1="18" y1="8" x2="21" y2="6" '
        'stroke="currentColor" stroke-width="1.5"/>'
        '<line x1="18" y1="12" x2="22" y2="12" '
        'stroke="currentColor" stroke-width="1.5"/>'
        '<line x1="18" y1="16" x2="21" y2="18" '
        'stroke="currentColor" stroke-width="1.5"/>'
        '</svg>'
    )


def _bell_icon() -> str:
    """Bell/siren/alarm icon."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<path d="M12,3 C12,3 7,4 7,10 L7,14 L4,17 L20,17 '
        'L17,14 L17,10 C17,4 12,3 12,3 Z" '
        'stroke="currentColor" stroke-width="1.5" fill="white" '
        'stroke-linejoin="round"/>'
        '<line x1="12" y1="1" x2="12" y2="3" '
        'stroke="currentColor" stroke-width="1.5"/>'
        '<path d="M10,17 Q10,21 12,21 Q14,21 14,17" '
        'stroke="currentColor" stroke-width="1.5" fill="none"/>'
        '</svg>'
    )


def _pull_station_icon() -> str:
    """Manual pull station / call station."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<rect x="4" y="2" width="16" height="20" rx="1.5" '
        'stroke="currentColor" stroke-width="1.5" fill="white"/>'
        '<line x1="12" y1="6" x2="12" y2="13" '
        'stroke="currentColor" stroke-width="2.5" stroke-linecap="round"/>'
        '<circle cx="12" cy="17" r="2.5" stroke="currentColor" '
        'stroke-width="1.5" fill="none"/>'
        '</svg>'
    )


def _telephone_icon() -> str:
    """Telephone icon — handset outline."""
    return (
        '<svg viewBox="0 0 24 24">'
        '<rect x="3" y="2" width="18" height="20" rx="2" '
        'stroke="currentColor" stroke-width="1.5" fill="white"/>'
        '<rect x="6" y="5" width="12" height="4" rx="1" '
        'stroke="currentColor" stroke-width="1" fill="none"/>'
        '<rect x="6" y="15" width="12" height="4" rx="1" '
        'stroke="currentColor" stroke-width="1" fill="none"/>'
        '<line x1="12" y1="9" x2="12" y2="15" '
        'stroke="currentColor" stroke-width="1" opacity="0.4"/>'
        '</svg>'
    )


# ── Device Name → Template Mapping ────────────────────────────────────


def get_device_icon(device_name: str, symbol_description: str = "") -> str:
    """Return a deterministic SVG icon for a fire alarm device.

    Matches the device name against known fire alarm categories and
    returns the appropriate SVG template. All icons use currentColor
    for automatic color-coding via CSS.

    Args:
        device_name: Device name from legend (e.g. "SMOKE DETECTOR")
        symbol_description: Optional description (unused — kept for interface compat)

    Returns:
        SVG markup string (always returns something — never None)
    """
    n = device_name.lower()

    # ── Combination detectors (check first) ───────────────────────
    if "smoke" in n and "heat" in n:
        return _circle_icon("SH")

    # ── Beam detectors ────────────────────────────────────────────
    if "beam" in n:
        if "transmit" in n:
            return _circle_icon("BT")
        if "receiv" in n:
            return _circle_icon("BR")
        return _circle_icon("BD")

    # ── Duct detectors ────────────────────────────────────────────
    if "duct" in n and "detect" in n:
        return _rect_icon("DD")

    # ── Specific detector types ───────────────────────────────────
    if "smoke" in n and "detect" in n:
        return _circle_icon("S")
    if "heat" in n and "detect" in n:
        return _circle_icon("H")
    if "flame" in n:
        return _circle_icon("FL")
    if ("carbon" in n or "co " in n or "co2" in n):
        return _circle_icon("CO")
    if "gas" in n and "detect" in n:
        return _circle_icon("G")
    if "smoke" in n:
        return _circle_icon("S")

    # ── Notification appliances ───────────────────────────────────
    if "speaker" in n or "loudspeaker" in n:
        return _speaker_icon()
    if "strobe" in n and ("horn" in n or "speaker" in n):
        return _horn_icon()
    if "strobe" in n:
        return _strobe_icon()
    if "horn" in n:
        return _horn_icon()
    if "siren" in n:
        return _bell_icon()
    if "bell" in n:
        return _bell_icon()
    if "sounder" in n or "chime" in n:
        return _bell_icon()

    # ── Manual devices ────────────────────────────────────────────
    if "pull" in n and "station" in n:
        return _pull_station_icon()
    if "call" in n and "station" in n:
        return _pull_station_icon()
    if "manual" in n and ("station" in n or "call" in n or "point" in n):
        return _pull_station_icon()
    if "telephone" in n or "phone" in n:
        return _telephone_icon()

    # ── Panels (specific before general) ──────────────────────────
    if "sub" in n and "panel" in n:
        return _panel_icon("SP")
    if "annunciator" in n:
        return _panel_icon("AN")
    if "control panel" in n or "facp" in n:
        return _panel_icon("FP")
    if "transponder" in n:
        return _rect_icon("TP")
    if "power supply" in n:
        return _rect_icon("PS")
    if "battery" in n:
        return _rect_icon("BT")

    # ── Modules ───────────────────────────────────────────────────
    if ("control" in n or "signal" in n) and "module" in n:
        return _rect_icon("CM")
    if "monitor" in n and "module" in n:
        return _rect_icon("MM")
    if "input" in n and "module" in n:
        return _rect_icon("IM")
    if "relay" in n and "module" in n:
        return _rect_icon("RM")
    if "isolat" in n and "module" in n:
        return _rect_icon("IS")
    if "module" in n:
        return _rect_icon("M")

    # ── Switches & valves ─────────────────────────────────────────
    if "flow" in n and ("switch" in n or "monitor" in n):
        return _diamond_icon("FS")
    if "tamper" in n:
        return _diamond_icon("TS")
    if "valve" in n:
        return _diamond_icon("V")
    if "switch" in n:
        return _diamond_icon("SW")

    # ── Remaining catch-alls ──────────────────────────────────────
    if "rack" in n:
        return _rect_icon("RK")
    if "junction" in n:
        return _rect_icon("JB")
    if "conduit" in n:
        return _rect_icon("C")
    if "detector" in n or "sensor" in n:
        return _circle_icon("D")
    if "panel" in n:
        return _panel_icon("P")

    # ── Default: first letter in a circle ─────────────────────────
    first = device_name.strip()[0].upper() if device_name.strip() else "?"
    return _circle_icon(first)


# ── Batch generation (keeps same interface) ───────────────────────────


async def generate_icons_batch(
    devices: list[dict],
) -> dict[str, str]:
    """Generate SVG icons for a batch of devices.

    Now deterministic (no API calls), so this is instant.

    Args:
        devices: List of dicts with 'name' and 'symbol_description' keys

    Returns:
        Dict mapping device name → SVG string (always succeeds for all)
    """
    results: dict[str, str] = {}
    for device in devices:
        name = device["name"]
        desc = device.get("symbol_description", "")
        svg = get_device_icon(name, desc)
        results[name] = svg
        icons_cache[name] = svg

    logger.info(
        f"[icon_gen] Generated {len(results)} icons (deterministic templates)"
    )
    return results
