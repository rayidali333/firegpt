"""
Drawing Preview Generator — Converts DXF geometry to interactive SVG.

Reads DXF entities (LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC) and converts
them to SVG elements. Returns the floor plan SVG separately from symbol
locations so the frontend can render interactive overlays.
"""

import math
from html import escape

import ezdxf

from app.models import SymbolInfo


def generate_drawing_preview(filepath: str, symbols: list[SymbolInfo]) -> dict:
    """Generate an SVG preview of the drawing floor plan."""
    try:
        doc = ezdxf.readfile(filepath)
    except Exception:
        try:
            doc, _ = ezdxf.recover.readfile(filepath)
        except Exception:
            return _empty_preview()

    svg_elements: list[str] = []
    all_x: list[float] = []
    all_y: list[float] = []

    # Scan ALL layouts (model space + paper space) for geometry
    for layout in doc.layouts:
        for entity in layout:
            _process_entity(entity, svg_elements, all_x, all_y)

    # Include symbol locations in bounds calculation
    for s in symbols:
        for x, y in s.locations:
            all_x.append(x)
            all_y.append(-y)

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
        f'preserveAspectRatio="xMidYMid meet" style="background:#FAFAFA">'
        f'<g stroke="#555" stroke-width="{stroke_w:.4f}" fill="none" '
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


def _process_entity(entity, elements: list, xs: list, ys: list):
    """Route an entity to the appropriate SVG handler."""
    etype = entity.dxftype()
    if etype == "LINE":
        _handle_line(entity, elements, xs, ys)
    elif etype == "LWPOLYLINE":
        _handle_lwpolyline(entity, elements, xs, ys)
    elif etype == "POLYLINE":
        _handle_polyline(entity, elements, xs, ys)
    elif etype == "CIRCLE":
        _handle_circle(entity, elements, xs, ys)
    elif etype == "ARC":
        _handle_arc(entity, elements, xs, ys)
    elif etype == "ELLIPSE":
        _handle_ellipse(entity, elements, xs, ys)
    elif etype == "SPLINE":
        _handle_spline(entity, elements, xs, ys)
    elif etype == "POINT":
        try:
            x, y = entity.dxf.location.x, entity.dxf.location.y
            xs.append(x)
            ys.append(-y)
        except Exception:
            pass


def _handle_line(entity, elements: list, xs: list, ys: list):
    x1, y1 = entity.dxf.start.x, -entity.dxf.start.y
    x2, y2 = entity.dxf.end.x, -entity.dxf.end.y
    elements.append(
        f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}"/>'
    )
    xs.extend([x1, x2])
    ys.extend([y1, y2])


def _handle_lwpolyline(entity, elements: list, xs: list, ys: list):
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
    elements.append(f'<{tag} points="{pts_str}"/>')


def _handle_polyline(entity, elements: list, xs: list, ys: list):
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
    elements.append(f'<{tag} points="{pts_str}"/>')


def _handle_circle(entity, elements: list, xs: list, ys: list):
    cx = entity.dxf.center.x
    cy = -entity.dxf.center.y
    r = entity.dxf.radius
    elements.append(f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}"/>')
    xs.extend([cx - r, cx + r])
    ys.extend([cy - r, cy + r])


def _handle_arc(entity, elements: list, xs: list, ys: list):
    cx = entity.dxf.center.x
    cy = -entity.dxf.center.y
    r = entity.dxf.radius
    # DXF: angles in degrees, counter-clockwise from positive X
    # SVG: Y is flipped, so arcs go clockwise
    start_deg = entity.dxf.start_angle
    end_deg = entity.dxf.end_angle
    start_rad = math.radians(start_deg)
    end_rad = math.radians(end_deg)

    # Start and end points (Y flipped)
    sx = cx + r * math.cos(start_rad)
    sy = cy - r * math.sin(start_rad)
    ex = cx + r * math.cos(end_rad)
    ey = cy - r * math.sin(end_rad)

    # Arc sweep angle
    sweep = (end_deg - start_deg) % 360
    large_arc = 1 if sweep > 180 else 0
    # Sweep direction: 0 = clockwise in SVG (counter-clockwise in DXF, flipped)
    sweep_flag = 0

    elements.append(
        f'<path d="M {sx:.2f} {sy:.2f} A {r:.2f} {r:.2f} 0 {large_arc} '
        f'{sweep_flag} {ex:.2f} {ey:.2f}"/>'
    )
    xs.extend([sx, ex])
    ys.extend([sy, ey])


def _handle_ellipse(entity, elements: list, xs: list, ys: list):
    try:
        center = entity.dxf.center
        cx, cy = center.x, -center.y
        major = entity.dxf.major_axis
        rx = math.sqrt(major.x ** 2 + major.y ** 2)
        ry = rx * entity.dxf.ratio
        rotation = math.degrees(math.atan2(major.y, major.x))
        elements.append(
            f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
            f'transform="rotate({-rotation:.2f} {cx:.2f} {cy:.2f})"/>'
        )
        xs.extend([cx - rx, cx + rx])
        ys.extend([cy - ry, cy + ry])
    except Exception:
        pass


def _handle_spline(entity, elements: list, xs: list, ys: list):
    try:
        # Approximate spline with control points as a polyline
        points = list(entity.control_points)
        if len(points) < 2:
            return
        pts = [(p.x, -p.y) for p in points]
        d = f"M {pts[0][0]:.2f} {pts[0][1]:.2f}"
        for x, y in pts[1:]:
            d += f" L {x:.2f} {y:.2f}"
        elements.append(f'<path d="{d}"/>')
        for x, y in pts:
            xs.append(x)
            ys.append(y)
    except Exception:
        pass
