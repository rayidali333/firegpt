"""
Drawing Preview Generator — Converts DXF geometry to interactive SVG.

Reads DXF entities (LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, INSERT, TEXT,
MTEXT, etc.) and converts them to SVG elements. INSERT entities are expanded
using ezdxf's virtual_entities() with a manual block definition fallback for
DWG→DXF converted files where virtual_entities() commonly fails.

Key features:
- Entity colors from DXF (ACI color index → hex, with BYLAYER resolution)
- TEXT/MTEXT rendering as SVG text elements
- Modelspace-only rendering (avoids paper space coordinate system conflicts)
- INSERT expansion: virtual_entities() first, manual block definition fallback
- SVG group transforms for manual block expansion (translate + scale + rotate)
- Element cap at 80K to prevent browser crashes
"""

import logging
import math
import re
from html import escape

import ezdxf

from app.models import SymbolInfo

logger = logging.getLogger(__name__)

MAX_SVG_ELEMENTS = 80000

# AutoCAD Color Index (ACI) standard colors → hex
ACI_COLORS = {
    1: "#FF0000",   # Red
    2: "#FFFF00",   # Yellow
    3: "#00FF00",   # Green
    4: "#00FFFF",   # Cyan
    5: "#0000FF",   # Blue
    6: "#FF00FF",   # Magenta
    7: "#333333",   # White (rendered dark on light background)
    8: "#808080",   # Dark gray
    9: "#C0C0C0",   # Light gray
    10: "#FF0000",  11: "#FF7F7F",  12: "#CC0000",
    20: "#FF3F00",  30: "#FF7F00",  40: "#FFBF00",
    50: "#FFFF00",  60: "#BFFF00",  70: "#7FFF00",
    80: "#3FFF00",  90: "#00FF00",  100: "#00FF3F",
    110: "#00FF7F", 120: "#00FFBF", 130: "#00FFFF",
    140: "#00BFFF", 150: "#007FFF", 160: "#003FFF",
    170: "#0000FF", 180: "#3F00FF", 190: "#7F00FF",
    200: "#BF00FF", 210: "#FF00FF", 220: "#FF00BF",
    230: "#FF007F", 240: "#FF003F", 250: "#333333",
    251: "#545454", 252: "#808080", 253: "#A0A0A0",
    254: "#C0C0C0", 255: "#FFFFFF",
}

# Entity types we can render as SVG
RENDERABLE_TYPES = {
    "LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
    "ELLIPSE", "SPLINE", "TEXT", "MTEXT", "POINT", "INSERT",
}


def _aci_to_hex(aci: int) -> str:
    """Convert AutoCAD Color Index to hex color."""
    if aci in ACI_COLORS:
        return ACI_COLORS[aci]
    try:
        from ezdxf.colors import DXF_DEFAULT_COLORS
        if 0 < aci < len(DXF_DEFAULT_COLORS):
            r, g, b = DXF_DEFAULT_COLORS[aci]
            return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        pass
    return "#555555"


def _resolve_color(entity, doc) -> str:
    """Resolve the effective color of an entity (handles BYLAYER, BYBLOCK)."""
    try:
        color = entity.dxf.get("color", 256)
        if color == 256:  # BYLAYER
            try:
                layer = doc.layers.get(entity.dxf.layer)
                color = layer.color
            except Exception:
                color = 7
        elif color == 0:  # BYBLOCK
            color = 7
        return _aci_to_hex(color)
    except Exception:
        return "#555555"


def generate_drawing_preview(filepath: str, symbols: list[SymbolInfo]) -> dict:
    """Generate an SVG preview of the drawing floor plan."""
    logger.info(f"Generating preview for: {filepath}")
    try:
        doc = ezdxf.readfile(filepath)
    except Exception as e:
        logger.warning(f"Normal read failed for preview ({e}), trying recovery mode")
        try:
            doc, _ = ezdxf.recover.readfile(filepath)
        except Exception as e2:
            logger.error(f"Recovery mode also failed for preview: {e2}")
            return _empty_preview()

    svg_elements: list[str] = []
    all_x: list[float] = []
    all_y: list[float] = []
    counter = [0]

    # Render modelspace ONLY. Paper space uses a different coordinate system
    # (paper units vs real-world units) which would stretch the viewbox.
    try:
        msp = doc.modelspace()
        for entity in msp:
            if counter[0] >= MAX_SVG_ELEMENTS:
                break
            _process_entity(entity, svg_elements, all_x, all_y, counter, doc=doc)
    except Exception:
        pass

    # If modelspace produced very few elements, try paper space as fallback.
    # Some DWG→DXF conversions put content in paper space.
    if len(svg_elements) < 20:
        for layout in doc.layouts:
            if layout.name == "Model":
                continue
            for entity in layout:
                if counter[0] >= MAX_SVG_ELEMENTS:
                    break
                _process_entity(entity, svg_elements, all_x, all_y, counter, doc=doc)

    # DO NOT include symbol overlay positions in SVG bounds.
    # The overlay SVG shares the same viewBox as the floor plan SVG.
    # Adding symbol positions from the parser (which may include paper space
    # coordinates from a different scale) would stretch the viewbox and make
    # the actual floor plan geometry appear as a tiny smudge.
    # The INSERT fallback positions from our own processing are already in
    # all_x/all_y and are sufficient for correct bounds.

    if not all_x or not all_y:
        # No geometry at all — fall back to symbol positions for bounds
        for s in symbols:
            for x, y in s.locations:
                all_x.append(x)
                all_y.append(-y)

    if not all_x or not all_y:
        return _empty_preview()

    # Filter outlier coordinates (>3 IQR from median) to prevent
    # stray points from stretching the viewbox
    all_x, all_y = _filter_outliers(all_x, all_y)

    if not all_x or not all_y:
        return _empty_preview()

    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)
    dx = max_x - min_x or 100
    dy = max_y - min_y or 100
    padding = max(dx, dy) * 0.04

    vb_x = min_x - padding
    vb_y = min_y - padding
    vb_w = dx + 2 * padding
    vb_h = dy + 2 * padding

    stroke_w = max(dx, dy) * 0.0008
    viewbox = f"{vb_x:.2f} {vb_y:.2f} {vb_w:.2f} {vb_h:.2f}"

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{viewbox}" '
        f'preserveAspectRatio="xMidYMid meet" '
        f'style="background:#FAFAFA" shape-rendering="geometricPrecision">'
        f'<g fill="none" stroke-width="{stroke_w:.4f}" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f'{"".join(svg_elements)}'
        f'</g></svg>'
    )

    return {
        "svg": svg,
        "viewBox": viewbox,
        "width": round(vb_w, 2),
        "height": round(vb_h, 2),
    }


def _empty_preview() -> dict:
    return {
        "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>',
        "viewBox": "0 0 100 100",
        "width": 100,
        "height": 100,
    }


def _filter_outliers(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    """Remove extreme outlier coordinates that would stretch the viewbox.

    Uses IQR-based filtering: points beyond Q1 - 3*IQR or Q3 + 3*IQR
    are considered outliers. This is robust against skewed distributions
    and handles the common case of a few paper-space coordinates mixed
    with model-space data.
    """
    if len(xs) < 4:
        return xs, ys

    def iqr_bounds(vals):
        s = sorted(vals)
        n = len(s)
        q1 = s[n // 4]
        q3 = s[3 * n // 4]
        iqr = q3 - q1
        if iqr <= 0:
            return min(vals), max(vals)
        margin = iqr * 3.0
        return q1 - margin, q3 + margin

    x_lo, x_hi = iqr_bounds(xs)
    y_lo, y_hi = iqr_bounds(ys)

    filtered_x = []
    filtered_y = []
    for x, y in zip(xs, ys):
        if x_lo <= x <= x_hi and y_lo <= y <= y_hi:
            filtered_x.append(x)
            filtered_y.append(y)

    return filtered_x or xs, filtered_y or ys


def _block_has_renderable_content(block) -> bool:
    """Check if a block definition contains any entities we can render."""
    for entity in block:
        if entity.dxftype() in RENDERABLE_TYPES:
            return True
    return False


def _process_entity(
    entity, elements: list, xs: list, ys: list,
    counter: list, depth: int = 0, doc=None,
):
    """Route an entity to the appropriate SVG handler."""
    if counter[0] >= MAX_SVG_ELEMENTS or depth > 8:
        return

    etype = entity.dxftype()

    if etype == "INSERT":
        _handle_insert(entity, elements, xs, ys, counter, depth, doc)
        return

    # Resolve entity color
    color = _resolve_color(entity, doc) if doc else "#555555"

    if etype == "LINE":
        _handle_line(entity, elements, xs, ys, counter, color)
    elif etype == "LWPOLYLINE":
        _handle_lwpolyline(entity, elements, xs, ys, counter, color)
    elif etype == "POLYLINE":
        _handle_polyline(entity, elements, xs, ys, counter, color)
    elif etype == "CIRCLE":
        _handle_circle(entity, elements, xs, ys, counter, color)
    elif etype == "ARC":
        _handle_arc(entity, elements, xs, ys, counter, color)
    elif etype == "ELLIPSE":
        _handle_ellipse(entity, elements, xs, ys, counter, color)
    elif etype == "SPLINE":
        _handle_spline(entity, elements, xs, ys, counter, color)
    elif etype == "TEXT":
        _handle_text(entity, elements, xs, ys, counter, color)
    elif etype == "MTEXT":
        _handle_mtext(entity, elements, xs, ys, counter, color)
    elif etype == "POINT":
        try:
            x, y = entity.dxf.location.x, entity.dxf.location.y
            xs.append(x)
            ys.append(-y)
        except Exception:
            pass


def _handle_insert(entity, elements: list, xs: list, ys: list,
                   counter: list, depth: int, doc):
    """Expand an INSERT entity into SVG elements.

    Strategy:
    1. Try ezdxf's virtual_entities() (handles all transforms automatically)
    2. If that fails, manually expand by reading the block definition and
       wrapping it in an SVG <g> with the INSERT's transform
    """
    expanded = False

    # Strategy 1: virtual_entities() — the official ezdxf way
    try:
        for ve in entity.virtual_entities():
            if counter[0] >= MAX_SVG_ELEMENTS:
                break
            try:
                _process_entity(ve, elements, xs, ys, counter, depth + 1, doc)
                expanded = True
            except Exception:
                continue
    except Exception:
        pass

    if expanded:
        return

    # Strategy 2: Manual block definition expansion with SVG transform.
    # After DWG→DXF conversion, virtual_entities() often fails because block
    # definitions are incomplete or contain unsupported entity types. But the
    # basic geometry (lines, polylines, circles) is usually preserved.
    if doc is not None:
        try:
            block_name = entity.dxf.name
            block = doc.blocks.get(block_name)
            if block is not None and _block_has_renderable_content(block):
                expanded = _manual_expand_block(
                    entity, block, elements, xs, ys, counter, depth, doc
                )
        except Exception:
            pass

    # Last resort: record insertion point for bounds calculation
    if not expanded:
        try:
            ix = entity.dxf.insert.x
            iy = -entity.dxf.insert.y
            xs.append(ix)
            ys.append(iy)
        except Exception:
            pass


def _manual_expand_block(entity, block, elements: list, xs: list, ys: list,
                         counter: list, depth: int, doc) -> bool:
    """Manually expand a block definition into SVG elements using SVG transforms.

    The key insight: sub-entities are processed normally (with Y-flip in each handler),
    then wrapped in an SVG <g> with the INSERT's translate/rotate/scale. The math works
    because:
    - Sub-entity at block-local (bx, by) renders as SVG (bx, -by)
    - SVG transform="translate(ix,-iy) rotate(-rot) scale(sx,sy)" applies:
      1. scale: (bx*sx, -by*sy)
      2. rotate(-rot): correct rotation in screen coords
      3. translate(ix,-iy): move to insertion point
    - Final position matches DXF coordinate math exactly.
    """
    # Get INSERT transform parameters
    ix = entity.dxf.insert.x
    iy = entity.dxf.insert.y
    sx = entity.dxf.get('xscale', 1.0)
    sy = entity.dxf.get('yscale', 1.0)
    rot = entity.dxf.get('rotation', 0.0)

    # Build SVG transform string
    transform_parts = [f"translate({ix:.2f},{-iy:.2f})"]
    if abs(rot) > 0.01:
        transform_parts.append(f"rotate({-rot:.2f})")
    if abs(sx - 1.0) > 0.001 or abs(sy - 1.0) > 0.001:
        transform_parts.append(f"scale({sx:.4f},{sy:.4f})")

    transform = " ".join(transform_parts)

    # Render sub-entities into a temporary list
    sub_elements: list[str] = []
    sub_xs: list[float] = []
    sub_ys: list[float] = []

    for sub_entity in block:
        if counter[0] >= MAX_SVG_ELEMENTS:
            break
        try:
            _process_entity(sub_entity, sub_elements, sub_xs, sub_ys,
                            counter, depth + 1, doc)
        except Exception:
            continue

    if not sub_elements:
        return False

    # Wrap in SVG group with transform
    elements.append(f'<g transform="{transform}">')
    elements.extend(sub_elements)
    elements.append('</g>')

    # Transform bounds: apply INSERT transform to sub-entity bounding box
    if sub_xs and sub_ys:
        _transform_bounds(ix, iy, sx, sy, rot, sub_xs, sub_ys, xs, ys)

    return True


def _transform_bounds(ix: float, iy: float, sx: float, sy: float, rot: float,
                      sub_xs: list[float], sub_ys: list[float],
                      xs: list[float], ys: list[float]):
    """Transform sub-entity bounds through the INSERT transform and add to parent bounds.

    sub_xs/sub_ys are in SVG coordinates (Y already flipped).
    We need to apply the SVG transform to get final screen coordinates.
    """
    cos_r = math.cos(math.radians(-rot)) if abs(rot) > 0.01 else 1.0
    sin_r = math.sin(math.radians(-rot)) if abs(rot) > 0.01 else 0.0

    # Transform the four corners of the bounding box
    bx_min, bx_max = min(sub_xs), max(sub_xs)
    by_min, by_max = min(sub_ys), max(sub_ys)

    corners = [
        (bx_min, by_min), (bx_max, by_min),
        (bx_min, by_max), (bx_max, by_max),
    ]

    for bx, by in corners:
        # Apply scale
        px = bx * sx
        py = by * sy
        # Apply rotation
        rx = px * cos_r - py * sin_r
        ry = px * sin_r + py * cos_r
        # Apply translation
        fx = rx + ix
        fy = ry + (-iy)
        xs.append(fx)
        ys.append(fy)


def _handle_line(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    x1, y1 = entity.dxf.start.x, -entity.dxf.start.y
    x2, y2 = entity.dxf.end.x, -entity.dxf.end.y
    elements.append(
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}"/>'
    )
    xs.extend([x1, x2])
    ys.extend([y1, y2])
    counter[0] += 1


def _handle_lwpolyline(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    try:
        points = list(entity.get_points(format="xy"))
    except Exception:
        return
    if len(points) < 2:
        return
    pts_str = " ".join(f"{x:.2f},{-y:.2f}" for x, y in points)
    for x, y in points:
        xs.append(x)
        ys.append(-y)
    tag = "polygon" if entity.closed else "polyline"
    elements.append(f'<{tag} points="{pts_str}" stroke="{color}"/>')
    counter[0] += 1


def _handle_polyline(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    try:
        vertices = [(v.dxf.location.x, v.dxf.location.y) for v in entity.vertices]
    except Exception:
        return
    if len(vertices) < 2:
        return
    pts_str = " ".join(f"{x:.2f},{-y:.2f}" for x, y in vertices)
    for x, y in vertices:
        xs.append(x)
        ys.append(-y)
    is_closed = getattr(entity, "is_closed", False)
    tag = "polygon" if is_closed else "polyline"
    elements.append(f'<{tag} points="{pts_str}" stroke="{color}"/>')
    counter[0] += 1


def _handle_circle(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    cx = entity.dxf.center.x
    cy = -entity.dxf.center.y
    r = entity.dxf.radius
    elements.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" stroke="{color}"/>')
    xs.extend([cx - r, cx + r])
    ys.extend([cy - r, cy + r])
    counter[0] += 1


def _handle_arc(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    cx = entity.dxf.center.x
    cy = -entity.dxf.center.y
    r = entity.dxf.radius
    start_deg = entity.dxf.start_angle
    end_deg = entity.dxf.end_angle
    start_rad = math.radians(start_deg)
    end_rad = math.radians(end_deg)

    sx = cx + r * math.cos(start_rad)
    sy = cy - r * math.sin(start_rad)
    ex = cx + r * math.cos(end_rad)
    ey = cy - r * math.sin(end_rad)

    sweep = (end_deg - start_deg) % 360
    large_arc = 1 if sweep > 180 else 0
    sweep_flag = 0

    elements.append(
        f'<path d="M {sx:.2f} {sy:.2f} A {r:.2f} {r:.2f} 0 {large_arc} '
        f'{sweep_flag} {ex:.2f} {ey:.2f}" stroke="{color}"/>'
    )
    xs.extend([sx, ex])
    ys.extend([sy, ey])
    counter[0] += 1


def _handle_ellipse(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    try:
        center = entity.dxf.center
        cx, cy = center.x, -center.y
        major = entity.dxf.major_axis
        rx = math.sqrt(major.x ** 2 + major.y ** 2)
        ry = rx * entity.dxf.ratio
        rotation = math.degrees(math.atan2(major.y, major.x))
        elements.append(
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
            f'transform="rotate({-rotation:.2f} {cx:.2f} {cy:.2f})" stroke="{color}"/>'
        )
        xs.extend([cx - rx, cx + rx])
        ys.extend([cy - ry, cy + ry])
        counter[0] += 1
    except Exception:
        pass


def _handle_spline(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    try:
        points = list(entity.control_points)
        if len(points) < 2:
            return
        pts = [(p.x, -p.y) for p in points]
        d = f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"
        for x, y in pts[1:]:
            d += f" L {x:.2f} {y:.2f}"
        elements.append(f'<path d="{d}" stroke="{color}"/>')
        for x, y in pts:
            xs.append(x)
            ys.append(y)
        counter[0] += 1
    except Exception:
        pass


def _handle_text(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    """Render DXF TEXT entity as SVG text."""
    try:
        text = entity.dxf.text
        if not text or not text.strip():
            return
        x = entity.dxf.insert.x
        y = -entity.dxf.insert.y
        height = entity.dxf.height
        rotation = getattr(entity.dxf, "rotation", 0)

        transform = ""
        if rotation:
            transform = f' transform="rotate({-rotation:.1f} {x:.2f} {y:.2f})"'

        escaped = escape(text)
        elements.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-size="{height:.2f}" '
            f'fill="{color}" stroke="none" font-family="Arial, sans-serif"'
            f'{transform}>{escaped}</text>'
        )
        xs.append(x)
        ys.append(y)
        counter[0] += 1
    except Exception:
        pass


def _handle_mtext(entity, elements: list, xs: list, ys: list, counter: list, color: str):
    """Render DXF MTEXT entity as SVG text (first line, formatting stripped)."""
    try:
        text = entity.text
        if not text or not text.strip():
            return
        # Strip MTEXT formatting codes
        text = re.sub(r"\\[PpNn]", "\n", text)           # Line breaks
        text = re.sub(r"\{[^}]*\}", "", text)             # Formatting groups
        text = re.sub(r"\\[A-Za-z][^;]*;", "", text)      # Formatting codes
        text = re.sub(r"\\[\\{}]", "", text)               # Escaped chars
        text = text.strip()
        if not text:
            return

        x = entity.dxf.insert.x
        y = -entity.dxf.insert.y
        height = entity.dxf.char_height
        rotation = getattr(entity.dxf, "rotation", 0)

        transform = ""
        if rotation:
            transform = f' transform="rotate({-rotation:.1f} {x:.2f} {y:.2f})"'

        # Render first line only (MTEXT can be very long)
        first_line = text.split("\n")[0][:100]
        escaped = escape(first_line)
        elements.append(
            f'<text x="{x:.2f}" y="{y:.2f}" font-size="{height:.2f}" '
            f'fill="{color}" stroke="none" font-family="Arial, sans-serif"'
            f'{transform}>{escaped}</text>'
        )
        xs.append(x)
        ys.append(y)
        counter[0] += 1
    except Exception:
        pass
