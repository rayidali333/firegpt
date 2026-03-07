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
    # Collect SVG-space positions for every INSERT block (block_name → [(x, y), ...])
    insert_positions: dict[str, list[tuple[float, float]]] = {}

    # Render modelspace ONLY. Paper space uses a different coordinate system
    # (paper units vs real-world units) which would stretch the viewbox.
    try:
        msp = doc.modelspace()
        for entity in msp:
            if counter[0] >= MAX_SVG_ELEMENTS:
                break
            _process_entity(entity, svg_elements, all_x, all_y, counter, doc=doc,
                            insert_positions=insert_positions)
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
                _process_entity(entity, svg_elements, all_x, all_y, counter, doc=doc,
                                insert_positions=insert_positions)

    position_debug: list[str] = []
    position_debug.append(f"SVG rendering: {counter[0]} elements (limit {MAX_SVG_ELEMENTS}), "
                          f"{len(insert_positions)} block types with positions from SVG pass")

    # ── Second pass: collect positions for fire alarm symbol blocks ──
    _collect_symbol_positions(doc, symbols, insert_positions, position_debug)

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

    # Map SVG-space insert positions to consolidated symbol block names.
    # The symbols list uses consolidated names ("A + B (+N variants)"),
    # while insert_positions uses raw DXF block names.
    symbol_svg_positions: dict[str, list[list[float]]] = {}
    for sym in symbols:
        positions = []
        # Check the consolidated block_name itself
        if sym.block_name in insert_positions:
            positions.extend(insert_positions[sym.block_name])
        # Check each variant block name
        for variant in (sym.block_variants or []):
            if variant in insert_positions:
                positions.extend(insert_positions[variant])
        if positions:
            # Deduplicate (in case block_name == a variant)
            seen = set()
            unique = []
            for p in positions:
                key = (p[0], p[1])
                if key not in seen:
                    seen.add(key)
                    unique.append([p[0], p[1]])
            symbol_svg_positions[sym.block_name] = unique

    total_inserts = sum(len(v) for v in insert_positions.values())
    logger.info(f"Preview: {len(insert_positions)} block types, {total_inserts} total INSERT positions, "
                f"mapped {len(symbol_svg_positions)} symbol types")

    # ── Fix-up: correct XREF coordinate offset ──
    # Some drawings place fire alarm symbols near the DXF origin while
    # architectural XREFs render the building at a large coordinate offset.
    # This detects the pattern and shifts out-of-bounds positions to align.
    _fixup_coordinate_offset(symbol_svg_positions, vb_x, vb_y, vb_w, vb_h,
                             position_debug)

    # ── Recovery pass: for symbols with 0 positions after schedule removal, ──
    # ── try raw entity.dxf.insert positions (may differ from renderable_geom ──
    # ── centroid when block geometry is offset from the block origin). ──
    missing_symbols = [sym for sym in symbols if sym.block_name not in symbol_svg_positions]
    if missing_symbols:
        missing_blocks: set[str] = set()
        for sym in missing_symbols:
            missing_blocks.add(sym.block_name)
            for v in (sym.block_variants or []):
                missing_blocks.add(v)

        try:
            msp = doc.modelspace()
            raw_positions: dict[str, list[list[float]]] = {}
            raw_samples: dict[str, tuple[float, float, float, float]] = {}  # block -> (raw_x, raw_y, rg_x, rg_y)
            for entity in msp:
                if entity.dxftype() not in ("INSERT", "MINSERT"):
                    continue
                bn = entity.dxf.name
                if bn not in missing_blocks:
                    continue
                try:
                    raw_x = round(entity.dxf.insert.x, 2)
                    raw_y = round(-entity.dxf.insert.y, 2)
                    raw_positions.setdefault(bn, []).append([raw_x, raw_y])
                    # Store first sample for diagnostic comparison
                    if bn not in raw_samples:
                        # Also get the renderable_geom position for comparison
                        rg_pos, _ = _compute_insert_svg_position_debug(entity, bn, doc)
                        rg_x, rg_y = rg_pos if rg_pos else (0.0, 0.0)
                        raw_samples[bn] = (raw_x, raw_y, rg_x, rg_y)
                except Exception:
                    pass

            # Map raw positions to symbol block names and check viewBox
            for sym in missing_symbols:
                positions: list[list[float]] = []
                if sym.block_name in raw_positions:
                    positions.extend(raw_positions[sym.block_name])
                for v in (sym.block_variants or []):
                    if v in raw_positions:
                        positions.extend(raw_positions[v])
                if not positions:
                    continue

                # Filter to in-viewBox positions
                in_vb = [p for p in positions
                         if vb_x <= p[0] <= vb_x + vb_w and vb_y <= p[1] <= vb_y + vb_h]
                if in_vb:
                    seen = set()
                    unique = []
                    for p in in_vb:
                        key = (p[0], p[1])
                        if key not in seen:
                            seen.add(key)
                            unique.append(p)
                    symbol_svg_positions[sym.block_name] = unique
                    position_debug.append(
                        f"  Raw INSERT recovery: {sym.label}: {len(unique)} positions "
                        f"(entity.dxf.insert differs from renderable_geom centroid)")
                else:
                    # Log diagnostic: raw positions vs renderable_geom
                    sample_bn = sym.block_name
                    if sample_bn not in raw_samples:
                        for v in (sym.block_variants or []):
                            if v in raw_samples:
                                sample_bn = v
                                break
                    if sample_bn in raw_samples:
                        rx, ry, rgx, rgy = raw_samples[sample_bn]
                        position_debug.append(
                            f"  Raw INSERT check {sym.label}: {len(positions)} total, 0 in viewBox. "
                            f"raw=({rx}, {ry}) vs renderable_geom=({rgx}, {rgy})")
                    else:
                        position_debug.append(
                            f"  Raw INSERT check {sym.label}: {len(positions)} total, 0 in viewBox, "
                            f"sample={positions[0]}")
        except Exception as e:
            position_debug.append(f"  Raw INSERT recovery failed: {e}")

    # Add per-symbol mapping debug info
    for sym in symbols:
        sp = symbol_svg_positions.get(sym.block_name)
        if sp:
            # Check if positions are within viewBox
            in_vb = sum(1 for px, py in sp
                        if vb_x <= px <= vb_x + vb_w and vb_y <= py <= vb_y + vb_h)
            unique_pts = len(set((p[0], p[1]) for p in sp))
            position_debug.append(
                f"→ {sym.label}: {len(sp)} positions ({in_vb} in viewBox, {unique_pts} unique)")
        else:
            position_debug.append(f"→ {sym.label}: 0 positions (NO MATCH in symbol_positions)")

    position_debug.append(f"viewBox: x={vb_x:.0f} y={vb_y:.0f} w={vb_w:.0f} h={vb_h:.0f}")

    return {
        "svg": svg,
        "viewBox": viewbox,
        "width": round(vb_w, 2),
        "height": round(vb_h, 2),
        "symbol_positions": symbol_svg_positions,
        "position_debug": position_debug,
    }


def _empty_preview() -> dict:
    return {
        "svg": '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>',
        "viewBox": "0 0 100 100",
        "width": 100,
        "height": 100,
        "symbol_positions": {},
        "position_debug": [],
    }


def _collect_symbol_positions(doc, symbols: list[SymbolInfo],
                              insert_positions: dict[str, list[tuple[float, float]]],
                              debug: list[str]):
    """Collect SVG-space positions for fire alarm symbol INSERT entities.

    This runs as a separate pass over modelspace with NO element counter limit.
    It's needed because the SVG rendering loop caps at MAX_SVG_ELEMENTS, which
    on complex architectural drawings is often reached before fire alarm symbol
    INSERTs are processed.

    Two scanning strategies:
    1. Direct scan: find target INSERTs directly in modelspace
    2. Nested scan: find target INSERTs inside container blocks (XREFs, etc.)
       and transform their positions to WCS
    """
    # Build full set of raw block names we need positions for
    all_target_blocks: set[str] = set()
    for sym in symbols:
        all_target_blocks.add(sym.block_name)
        for v in (sym.block_variants or []):
            all_target_blocks.add(v)

    target_blocks = all_target_blocks.copy()
    already_have = target_blocks & set(insert_positions.keys())
    target_blocks -= already_have

    debug.append(f"Position pass: {len(already_have)} block types from SVG pass, "
                 f"{len(target_blocks)} need 2nd pass")

    if not target_blocks:
        return

    try:
        msp = doc.modelspace()
    except Exception:
        debug.append("ERROR: Cannot access modelspace for 2nd pass")
        return

    # ── Direct scan: find target INSERTs in modelspace ──
    # Uses both exact matching and XREF-prefix fuzzy matching.
    # Also handles MINSERT entities (arrayed block insertions).
    method_stats: dict[str, dict[str, int]] = {}
    found = 0
    xref_matched = 0
    for entity in msp:
        if entity.dxftype() not in ("INSERT", "MINSERT"):
            continue
        block_name = entity.dxf.name
        if block_name in target_blocks:
            matched_name = block_name
        else:
            # Fuzzy match: handles XREF-prefixed names (XREFNAME$0$TARGETBLOCK)
            matched_name = _match_target_block(block_name, target_blocks)
            if matched_name is None:
                continue
            xref_matched += 1

        pos, method = _compute_insert_svg_position_debug(entity, block_name, doc)
        if pos:
            insert_positions.setdefault(matched_name, []).append(pos)
            method_stats.setdefault(matched_name, {})
            method_stats[matched_name][method] = method_stats[matched_name].get(method, 0) + 1
            found += 1

    for bn, methods in method_stats.items():
        total = sum(methods.values())
        methods_str = ", ".join(f"{m}:{c}" for m, c in methods.items())
        sample = insert_positions[bn][0] if bn in insert_positions else "N/A"
        debug.append(f"  {bn[:50]}: {total} positions [{methods_str}] sample={sample}")

    for bn in target_blocks:
        if bn not in insert_positions:
            debug.append(f"  {bn[:50]}: 0 positions (NO METHOD WORKED)")

    logger.info(f"Direct scan: found {found} positions, "
                f"{sum(1 for b in target_blocks if b in insert_positions)} block types"
                f"{f', {xref_matched} XREF-prefix matches' if xref_matched else ''}")

    # ── Diagnostic: find fire-alarm-keyword INSERTs in modelspace that weren't matched ──
    _FA_KEYWORDS = {"DETECTOR", "SMOKE", "HEAT", "SPEAKER", "STROBE", "SIREN",
                    "HORN", "PULL STATION", "MANUAL STATION", "MONITOR MODULE",
                    "CONTROL MODULE", "FIRE ALARM"}
    unmatched_fa: dict[str, list] = {}
    for entity in msp:
        if entity.dxftype() not in ("INSERT", "MINSERT"):
            continue
        bn = entity.dxf.name
        if bn in all_target_blocks or bn in insert_positions:
            continue
        bn_upper = bn.upper()
        if any(kw in bn_upper for kw in _FA_KEYWORDS):
            if bn not in unmatched_fa:
                try:
                    x, y = entity.dxf.insert.x, entity.dxf.insert.y
                    unmatched_fa[bn] = [0, x, y]
                except Exception:
                    unmatched_fa[bn] = [0, 0, 0]
            unmatched_fa[bn][0] += 1
    if unmatched_fa:
        debug.append("Unmatched fire-alarm INSERTs in modelspace:")
        for bn, (cnt, sx, sy) in sorted(unmatched_fa.items(), key=lambda x: -x[1][0])[:10]:
            debug.append(f"  {bn[:70]}: {cnt} at sample=({sx:.1f}, {sy:.1f})")

    # ── Nested scan: find target INSERTs inside container blocks (XREFs) ──
    _collect_nested_symbol_positions(doc, all_target_blocks, insert_positions, debug)


def _strip_xref_prefix(name: str) -> str:
    """Strip bound XREF prefix from a block name.

    AutoCAD renames blocks when binding XREFs: XREFNAME$0$ORIGINAL_NAME.
    Multiple binding levels produce: OUTER$0$INNER$0$NAME.
    ODA File Converter may use other formats: XREF|NAME, XREF`NAME.
    """
    # AutoCAD standard: last $0$ separator
    idx = name.rfind('$0$')
    if idx >= 0:
        return name[idx + 3:]
    # ODA/other converters
    for sep in ('|', '`'):
        idx = name.rfind(sep)
        if idx > 0:
            return name[idx + 1:]
    return name


def _match_target_block(child_name: str, all_target_blocks: set[str]) -> str | None:
    """Match an INSERT block name against target blocks, handling XREF prefixes.

    Returns the matched target block name, or None if no match.
    Handles multiple XREF binding formats:
    - AutoCAD: XREFNAME$0$ORIGINAL_NAME (possibly multi-level)
    - ODA/other: XREFNAME|ORIGINAL_NAME, XREFNAME`ORIGINAL_NAME
    """
    # Exact match
    if child_name in all_target_blocks:
        return child_name

    # Strip XREF binding prefix and try again
    stripped = _strip_xref_prefix(child_name)
    if stripped != child_name and stripped in all_target_blocks:
        return stripped

    # Try all $0$ split positions (multi-level XREF: A$0$B$0$C)
    if '$0$' in child_name:
        parts = child_name.split('$0$')
        for i in range(1, len(parts)):
            suffix = '$0$'.join(parts[i:])
            if suffix in all_target_blocks:
                return suffix

    # Try other common XREF separator formats (ODA, BricsCAD, etc.)
    for sep in ('|', '`', '$'):
        idx = child_name.rfind(sep)
        if idx > 0:
            suffix = child_name[idx + len(sep):]
            if suffix in all_target_blocks:
                return suffix

    # Case-insensitive match after stripping prefix
    if stripped != child_name:
        stripped_upper = stripped.upper()
        for target in all_target_blocks:
            if target.upper() == stripped_upper:
                return target

    # Check if any target name is a suffix of the child name (handles
    # multi-level XREF prefixes or unusual naming)
    for target in all_target_blocks:
        if child_name.endswith(target) and len(child_name) > len(target):
            sep_char = child_name[-(len(target) + 1)]
            if sep_char in ('$', '_', '-', '|', '`'):
                return target

    return None


def _collect_nested_symbol_positions(doc, all_target_blocks: set[str],
                                     insert_positions: dict[str, list[tuple[float, float]]],
                                     debug: list[str]):
    """Find fire alarm INSERTs nested inside container blocks (XREFs, etc.)
    and compute their WCS positions.

    Many DXF/DWG files place fire alarm symbols inside XREFs or other container
    blocks. The direct modelspace scan finds INSERTs at block-local coords (near 0),
    but the actual visible positions are at the XREF's insertion point + local offset.

    This function:
    1. Scans all block definitions for target fire alarm INSERT entities
       (including XREF-prefixed names like XREFNAME$0$BLOCKNAME)
    2. Builds a hierarchy of container blocks
    3. For each container found in modelspace, recursively transforms nested
       target positions to WCS
    """
    SKIP_PREFIXES = ("*Model_Space", "*Paper_Space")

    # Step 1: Find block definitions that directly contain target INSERTs
    # direct_targets[container_name] = [(matched_target_name, insert_x, insert_y), ...]
    direct_targets: dict[str, list[tuple[str, float, float]]] = {}
    xref_matches: int = 0

    for block in doc.blocks:
        bn = block.name
        if any(bn.startswith(p) for p in SKIP_PREFIXES):
            continue
        if bn in all_target_blocks:
            continue
        for ent in block:
            if ent.dxftype() not in ("INSERT", "MINSERT"):
                continue
            child_name = ent.dxf.name
            matched = _match_target_block(child_name, all_target_blocks)
            if matched is None:
                continue
            if matched != child_name:
                xref_matches += 1
            try:
                direct_targets.setdefault(bn, []).append(
                    (matched, ent.dxf.insert.x, ent.dxf.insert.y))
            except Exception:
                pass

    if not direct_targets:
        # Log diagnostic info about what blocks contain INSERT entities
        insert_blocks = []
        for block in doc.blocks:
            bn = block.name
            if any(bn.startswith(p) for p in SKIP_PREFIXES):
                continue
            insert_count = sum(1 for e in block if e.dxftype() == "INSERT")
            if insert_count > 5:
                insert_blocks.append((bn, insert_count))
        insert_blocks.sort(key=lambda x: -x[1])
        if insert_blocks:
            debug.append(f"Nested scan: no container blocks found. "
                         f"Blocks with INSERTs: {', '.join(f'{n[:40]}({c})' for n, c in insert_blocks[:5])}")
        else:
            debug.append("Nested scan: no container blocks found (no blocks contain INSERT entities)")

        # Enhanced diagnostic: check if XREF blocks contain fire-alarm-keyword INSERTs
        _FA_KW_NESTED = {"DETECTOR", "SMOKE", "HEAT", "SPEAKER", "STROBE", "SIREN",
                         "HORN", "PULL", "MANUAL", "MONITOR", "FIRE ALARM", "MODULE"}
        fa_in_blocks = False
        for block in doc.blocks:
            bn = block.name
            if any(bn.startswith(p) for p in SKIP_PREFIXES):
                continue
            fa_inserts: dict[str, int] = {}
            for e in block:
                if e.dxftype() != "INSERT":
                    continue
                cn = e.dxf.name
                cn_upper = cn.upper()
                if any(kw in cn_upper for kw in _FA_KW_NESTED):
                    fa_inserts[cn] = fa_inserts.get(cn, 0) + 1
            if fa_inserts:
                fa_in_blocks = True
                debug.append(f"  Block '{bn[:50]}' has fire-alarm INSERTs:")
                for n, c in sorted(fa_inserts.items(), key=lambda x: -x[1])[:5]:
                    debug.append(f"    {n[:70]}: {c}")
        if not fa_in_blocks:
            debug.append("  No fire-alarm-keyword INSERTs found in ANY block definition")

            # Last resort: dump ALL unique INSERT names from top XREF blocks
            for bn, cnt in insert_blocks[:3]:
                try:
                    blk = doc.blocks.get(bn)
                    if blk:
                        sample_names: dict[str, int] = {}
                        for e in blk:
                            if e.dxftype() == "INSERT":
                                sample_names[e.dxf.name] = sample_names.get(e.dxf.name, 0) + 1
                        top_names = sorted(sample_names.items(), key=lambda x: -x[1])[:8]
                        debug.append(f"  Block '{bn[:40]}' top INSERT names:")
                        for n, c in top_names:
                            debug.append(f"    {n[:70]}: {c}")
                except Exception:
                    pass
        return

    # Step 2: Find higher-level containers (blocks that contain the direct containers)
    # This handles multi-level nesting: Outer XREF → Inner XREF → Fire alarm block
    # container_links[outer_name] = [(inner_name, x, y, xscale, yscale, rotation), ...]
    reachable: set[str] = set(direct_targets.keys())
    container_links: dict[str, list[tuple[str, float, float, float, float, float]]] = {}

    for _level in range(3):
        found_new = False
        for block in doc.blocks:
            bn = block.name
            if any(bn.startswith(p) for p in SKIP_PREFIXES):
                continue
            if bn in reachable or bn in all_target_blocks:
                continue
            for ent in block:
                if ent.dxftype() not in ("INSERT", "MINSERT") or ent.dxf.name not in reachable:
                    continue
                try:
                    container_links.setdefault(bn, []).append((
                        ent.dxf.name,
                        ent.dxf.insert.x, ent.dxf.insert.y,
                        ent.dxf.get("xscale", 1.0),
                        ent.dxf.get("yscale", 1.0),
                        ent.dxf.get("rotation", 0.0),
                    ))
                    if bn not in reachable:
                        reachable.add(bn)
                        found_new = True
                except Exception:
                    pass
        if not found_new:
            break

    debug.append(f"Nested scan: {len(direct_targets)} direct containers, "
                 f"{len(reachable)} total reachable blocks"
                 f"{f', {xref_matches} XREF-prefixed matches' if xref_matches else ''}")
    for cn in list(direct_targets.keys())[:5]:
        debug.append(f"  Container '{cn[:60]}': {len(direct_targets[cn])} target INSERTs")

    # Step 3: Scan modelspace for container INSERTs and resolve nested targets
    try:
        msp = doc.modelspace()
    except Exception:
        debug.append("Nested scan: ERROR cannot access modelspace")
        return

    nested_count = 0
    for entity in msp:
        if entity.dxftype() not in ("INSERT", "MINSERT"):
            continue
        bn = entity.dxf.name
        if bn not in reachable:
            continue

        try:
            tx = entity.dxf.insert.x
            ty = entity.dxf.insert.y
            sx = entity.dxf.get("xscale", 1.0)
            sy = entity.dxf.get("yscale", 1.0)
            rot = entity.dxf.get("rotation", 0.0)
        except Exception:
            continue

        nested_count += _resolve_nested_targets(
            doc, bn, direct_targets, container_links, insert_positions,
            tx, ty, sx, sy, rot, depth=0)

    debug.append(f"Nested scan: {nested_count} positions from nested INSERTs")


def _resolve_nested_targets(doc, block_name: str,
                            direct_targets: dict, container_links: dict,
                            insert_positions: dict,
                            tx: float, ty: float,
                            sx: float, sy: float, rot_deg: float,
                            depth: int) -> int:
    """Recursively resolve target INSERT positions inside a container block."""
    if depth > 5:
        return 0

    # Get this block's base_point
    bp_x = bp_y = 0.0
    try:
        blk = doc.blocks.get(block_name)
        if blk:
            bp_x, bp_y = blk.base_point.x, blk.base_point.y
    except Exception:
        pass

    count = 0

    # Process direct target children in this block
    if block_name in direct_targets:
        for child_name, cx, cy in direct_targets[block_name]:
            wcs_x, wcs_y = _apply_insert_transform(
                cx, cy, tx, ty, sx, sy, rot_deg, bp_x, bp_y)
            svg_pos = (round(wcs_x, 2), round(-wcs_y, 2))
            insert_positions.setdefault(child_name, []).append(svg_pos)
            count += 1

    # Process container children (blocks that themselves contain targets)
    if block_name in container_links:
        for child_name, cx, cy, csx, csy, crot in container_links[block_name]:
            # Transform this child container's position to WCS
            child_wcs_x, child_wcs_y = _apply_insert_transform(
                cx, cy, tx, ty, sx, sy, rot_deg, bp_x, bp_y)
            # Cumulative scale and rotation
            cum_sx = sx * csx
            cum_sy = sy * csy
            cum_rot = rot_deg + crot
            # Recurse into child container
            count += _resolve_nested_targets(
                doc, child_name, direct_targets, container_links,
                insert_positions,
                child_wcs_x, child_wcs_y, cum_sx, cum_sy, cum_rot,
                depth + 1)

    return count


def _apply_insert_transform(cx: float, cy: float,
                            tx: float, ty: float,
                            sx: float, sy: float,
                            rot_deg: float,
                            bp_x: float, bp_y: float) -> tuple[float, float]:
    """Transform a child INSERT's local position to WCS.

    WCS = parent_insert + R(rotation) * S(scale) * (child_pos - base_point)
    """
    # Offset from block base_point
    lx = cx - bp_x
    ly = cy - bp_y

    # Apply scale
    slx = lx * sx
    sly = ly * sy

    # Apply rotation
    if abs(rot_deg) > 0.01:
        rad = math.radians(rot_deg)
        cos_r = math.cos(rad)
        sin_r = math.sin(rad)
        rx = slx * cos_r - sly * sin_r
        ry = slx * sin_r + sly * cos_r
    else:
        rx, ry = slx, sly

    return tx + rx, ty + ry


def _fixup_coordinate_offset(symbol_positions: dict[str, list[list[float]]],
                              vb_x: float, vb_y: float,
                              vb_w: float, vb_h: float,
                              debug: list[str]):
    """Fix symbol positions systematically offset from the viewBox.

    Handles two cases:
    1. **Schedule positions**: INSERTs arranged in a vertical/horizontal line
       (device schedule or legend). These are NOT floor plan placements and
       should be removed entirely.
    2. **Offset positions**: Real placements that are simply offset from the
       viewBox due to XREF coordinate transforms. These can be shifted.
    """
    if not symbol_positions:
        return

    # ── Step 1: Detect and remove schedule-like (degenerate) positions ──
    # Per symbol type: if out-of-viewBox positions form a line (all same X or
    # all same Y), they're from a device schedule, not floor plan placements.
    schedule_removed = 0
    for block_name in list(symbol_positions.keys()):
        positions = symbol_positions[block_name]
        if len(positions) < 3:
            continue

        in_vb = []
        out_vb = []
        for p in positions:
            if vb_x <= p[0] <= vb_x + vb_w and vb_y <= p[1] <= vb_y + vb_h:
                in_vb.append(p)
            else:
                out_vb.append(p)

        if len(out_vb) < 3:
            continue

        # Check if out-of-viewBox positions are degenerate (form a line)
        out_xs = [p[0] for p in out_vb]
        out_ys = [p[1] for p in out_vb]
        x_range = max(out_xs) - min(out_xs)
        y_range = max(out_ys) - min(out_ys)
        max_range = max(x_range, y_range, 1.0)
        min_range = min(x_range, y_range)

        if min_range / max_range < 0.02:
            # Degenerate: all positions at nearly the same X (or Y)
            # These are schedule/legend entries, not floor plan placements
            if in_vb:
                symbol_positions[block_name] = in_vb
                debug.append(f"  Schedule fix: removed {len(out_vb)} schedule positions "
                             f"for {block_name[:50]}, kept {len(in_vb)} floor plan positions")
            else:
                del symbol_positions[block_name]
                debug.append(f"  Schedule fix: removed all {len(positions)} schedule positions "
                             f"for {block_name[:50]} (x_range={x_range:.0f}, y_range={y_range:.0f})")
            schedule_removed += len(out_vb)

    if schedule_removed:
        debug.append(f"Schedule detection: removed {schedule_removed} schedule/legend positions total")

    # ── Step 2: For remaining non-degenerate out-of-bounds positions, ──
    # ── try to shift them into the viewBox ──
    in_bounds: list[tuple[float, float]] = []
    out_bounds: list[tuple[float, float]] = []

    for positions in symbol_positions.values():
        for x, y in positions:
            if vb_x <= x <= vb_x + vb_w and vb_y <= y <= vb_y + vb_h:
                in_bounds.append((x, y))
            else:
                out_bounds.append((x, y))

    total = len(in_bounds) + len(out_bounds)
    if total == 0 or len(out_bounds) == 0:
        return

    out_ratio = len(out_bounds) / total
    if out_ratio < 0.15:
        return  # Only a few outliers, not a systematic offset

    # Compute per-dimension offset
    out_xs = [x for x, _ in out_bounds]
    out_ys = [y for _, y in out_bounds]
    out_cx = sum(out_xs) / len(out_xs)
    out_cy = sum(out_ys) / len(out_ys)

    if in_bounds:
        anchor_x = sum(x for x, _ in in_bounds) / len(in_bounds)
        anchor_y = sum(y for _, y in in_bounds) / len(in_bounds)
    else:
        anchor_x = vb_x + vb_w / 2
        anchor_y = vb_y + vb_h / 2

    offset_x = (anchor_x - out_cx) if (out_cx < vb_x or out_cx > vb_x + vb_w) else 0.0
    offset_y = (anchor_y - out_cy) if (out_cy < vb_y or out_cy > vb_y + vb_h) else 0.0

    if abs(offset_x) < 100 and abs(offset_y) < 100:
        return

    # Validate offset brings most positions into viewBox
    margin_x, margin_y = vb_w * 0.1, vb_h * 0.1
    test_in = sum(
        1 for x, y in out_bounds
        if (vb_x - margin_x <= x + offset_x <= vb_x + vb_w + margin_x and
            vb_y - margin_y <= y + offset_y <= vb_y + vb_h + margin_y)
    )

    if test_in < len(out_bounds) * 0.5:
        debug.append(f"Coordinate offset fix: offset ({offset_x:.0f}, {offset_y:.0f}) "
                     f"only fixes {test_in}/{len(out_bounds)}, skipping")
        return

    # Apply offset to remaining out-of-bounds positions
    fixed = 0
    for positions in symbol_positions.values():
        for i, pos in enumerate(positions):
            x, y = pos[0], pos[1]
            if vb_x <= x <= vb_x + vb_w and vb_y <= y <= vb_y + vb_h:
                continue
            positions[i] = [round(x + offset_x, 2), round(y + offset_y, 2)]
            fixed += 1

    debug.append(f"Coordinate offset fix: shifted {fixed}/{len(out_bounds)} positions "
                 f"by ({offset_x:.0f}, {offset_y:.0f})")


def _compute_insert_svg_position_debug(entity, block_name: str, doc) -> tuple[tuple[float, float] | None, str]:
    """Like _compute_insert_svg_position but also returns which method was used."""
    # Method 1: Centroid from renderable virtual entities
    POSITION_TYPES = {
        "LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
        "ELLIPSE", "SPLINE", "TEXT", "MTEXT", "POINT",
    }
    try:
        pts_x: list[float] = []
        pts_y: list[float] = []
        count = 0
        for ve in entity.virtual_entities():
            count += 1
            if count > 500:
                break
            vtype = ve.dxftype()
            if vtype not in POSITION_TYPES:
                continue
            try:
                dxf = ve.dxf
                if vtype == "LINE":
                    pts_x.append(dxf.start.x); pts_y.append(-dxf.start.y)
                elif vtype in ("CIRCLE", "ARC"):
                    pts_x.append(dxf.center.x); pts_y.append(-dxf.center.y)
                elif vtype in ("TEXT", "MTEXT"):
                    pts_x.append(dxf.insert.x); pts_y.append(-dxf.insert.y)
                elif vtype == "POINT":
                    pts_x.append(dxf.location.x); pts_y.append(-dxf.location.y)
                elif vtype in ("ELLIPSE", "SPLINE"):
                    if hasattr(dxf, 'center'):
                        pts_x.append(dxf.center.x); pts_y.append(-dxf.center.y)
                elif vtype in ("LWPOLYLINE", "POLYLINE"):
                    try:
                        if vtype == "LWPOLYLINE":
                            points = list(ve.get_points(format="xy"))
                        else:
                            points = [(v.dxf.location.x, v.dxf.location.y) for v in ve.vertices]
                        if points:
                            pts_x.append(points[0][0]); pts_y.append(-points[0][1])
                    except Exception:
                        pass
            except Exception:
                continue
        if pts_x and pts_y:
            cx = (min(pts_x) + max(pts_x)) / 2
            cy = (min(pts_y) + max(pts_y)) / 2
            return (round(cx, 2), round(cy, 2)), "renderable_geom"
    except Exception:
        pass

    # Method 2: ATTRIB instances (WCS coordinates)
    try:
        if hasattr(entity, 'attribs'):
            attrib_x: list[float] = []
            attrib_y: list[float] = []
            for attrib in entity.attribs:
                try:
                    attrib_x.append(attrib.dxf.insert.x)
                    attrib_y.append(-attrib.dxf.insert.y)
                except Exception:
                    continue
            if attrib_x and attrib_y:
                cx = (min(attrib_x) + max(attrib_x)) / 2
                cy = (min(attrib_y) + max(attrib_y)) / 2
                return (round(cx, 2), round(cy, 2)), "attrib_wcs"
    except Exception:
        pass

    # Method 3: Base_point-adjusted insertion point
    pos = _get_adjusted_insert_position(entity, block_name, doc)
    return pos, "base_point_adj"


def _compute_insert_svg_position(entity, block_name: str, doc) -> tuple[float, float] | None:
    """Compute the SVG-space (x, -y) position of an INSERT entity.

    Strategy:
    1. virtual_entities centroid from RENDERABLE types only (LINE, CIRCLE, etc.)
       These are correctly transformed to WCS by ezdxf.
       EXCLUDES ATTDEF entities which stay in block-local space.
    2. ATTRIB instances attached to the INSERT (these ARE in WCS)
    3. Base_point-adjusted insertion point as last resort
    """
    # Method 1: Centroid from renderable virtual entities only
    POSITION_TYPES = {
        "LINE", "LWPOLYLINE", "POLYLINE", "CIRCLE", "ARC",
        "ELLIPSE", "SPLINE", "TEXT", "MTEXT", "POINT",
    }
    try:
        pts_x: list[float] = []
        pts_y: list[float] = []
        count = 0
        for ve in entity.virtual_entities():
            count += 1
            if count > 500:
                break
            vtype = ve.dxftype()
            if vtype not in POSITION_TYPES:
                continue  # Skip ATTDEF, ATTRIB from virtual_entities (block-local coords)
            try:
                dxf = ve.dxf
                if vtype == "LINE":
                    pts_x.append(dxf.start.x)
                    pts_y.append(-dxf.start.y)
                elif vtype in ("CIRCLE", "ARC"):
                    pts_x.append(dxf.center.x)
                    pts_y.append(-dxf.center.y)
                elif vtype in ("TEXT", "MTEXT"):
                    pts_x.append(dxf.insert.x)
                    pts_y.append(-dxf.insert.y)
                elif vtype == "POINT":
                    pts_x.append(dxf.location.x)
                    pts_y.append(-dxf.location.y)
                elif vtype in ("ELLIPSE", "SPLINE"):
                    if hasattr(dxf, 'center'):
                        pts_x.append(dxf.center.x)
                        pts_y.append(-dxf.center.y)
                elif vtype in ("LWPOLYLINE", "POLYLINE"):
                    try:
                        if vtype == "LWPOLYLINE":
                            points = list(ve.get_points(format="xy"))
                        else:
                            points = [(v.dxf.location.x, v.dxf.location.y) for v in ve.vertices]
                        if points:
                            pts_x.append(points[0][0])
                            pts_y.append(-points[0][1])
                    except Exception:
                        pass
            except Exception:
                continue
        if pts_x and pts_y:
            cx = (min(pts_x) + max(pts_x)) / 2
            cy = (min(pts_y) + max(pts_y)) / 2
            return (round(cx, 2), round(cy, 2))
    except Exception:
        pass

    # Method 2: ATTRIB instances attached to the INSERT entity
    # ATTRIBs (unlike ATTDEFs from virtual_entities) have WCS coordinates
    # that are unique per INSERT instance
    try:
        if hasattr(entity, 'attribs'):
            attrib_x: list[float] = []
            attrib_y: list[float] = []
            for attrib in entity.attribs:
                try:
                    attrib_x.append(attrib.dxf.insert.x)
                    attrib_y.append(-attrib.dxf.insert.y)
                except Exception:
                    continue
            if attrib_x and attrib_y:
                cx = (min(attrib_x) + max(attrib_x)) / 2
                cy = (min(attrib_y) + max(attrib_y)) / 2
                return (round(cx, 2), round(cy, 2))
    except Exception:
        pass

    # Method 3: Base_point-adjusted insertion point
    return _get_adjusted_insert_position(entity, block_name, doc)


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


def _extract_position(entity, xs: list, ys: list):
    """Extract position from non-renderable entity types for bounds/position tracking.

    Handles ATTDEF, ATTRIB, SOLID, DIMENSION, LEADER, etc. These don't produce
    SVG elements but have position data needed for INSERT centroid computation.
    """
    try:
        dxf = entity.dxf
        if hasattr(dxf, 'insert'):
            xs.append(dxf.insert.x)
            ys.append(-dxf.insert.y)
        elif hasattr(dxf, 'location'):
            xs.append(dxf.location.x)
            ys.append(-dxf.location.y)
        elif hasattr(dxf, 'center'):
            xs.append(dxf.center.x)
            ys.append(-dxf.center.y)
        elif hasattr(dxf, 'start'):
            xs.append(dxf.start.x)
            ys.append(-dxf.start.y)
    except Exception:
        pass


def _get_adjusted_insert_position(entity, block_name: str, doc) -> tuple[float, float]:
    """Compute the SVG-space position of an INSERT entity, adjusted for block base_point.

    DWG blocks often have large base_point offsets. The raw insertion point
    (entity.dxf.insert) is NOT where the visual content appears. The actual
    world position is: insert_point + rotation(scale(-base_point)).
    For simple cases (no rotation, scale=1): insert_point - base_point.
    """
    ix = entity.dxf.insert.x
    iy = entity.dxf.insert.y

    if doc is not None:
        try:
            block = doc.blocks.get(block_name)
            if block is not None:
                base = block.base_point
                bx, by = base.x, base.y
                if abs(bx) > 0.01 or abs(by) > 0.01:
                    sx = entity.dxf.get('xscale', 1.0)
                    sy = entity.dxf.get('yscale', 1.0)
                    rot = entity.dxf.get('rotation', 0.0)

                    # Transform -base_point through scale and rotation
                    dx = -bx * sx
                    dy = -by * sy

                    if abs(rot) > 0.01:
                        rad = math.radians(rot)
                        cos_r = math.cos(rad)
                        sin_r = math.sin(rad)
                        rdx = dx * cos_r - dy * sin_r
                        rdy = dx * sin_r + dy * cos_r
                        dx, dy = rdx, rdy

                    ix += dx
                    iy += dy
        except Exception:
            pass

    return (ix, -iy)


def _record_adjusted_insert_position(entity, block_name: str, doc, insert_positions: dict):
    """Record the base_point-adjusted SVG position for an INSERT entity."""
    try:
        adj_x, adj_y = _get_adjusted_insert_position(entity, block_name, doc)
        insert_positions.setdefault(block_name, []).append((round(adj_x, 2), round(adj_y, 2)))
    except Exception:
        pass


def _process_entity(
    entity, elements: list, xs: list, ys: list,
    counter: list, depth: int = 0, doc=None,
    insert_positions: dict | None = None,
):
    """Route an entity to the appropriate SVG handler."""
    if counter[0] >= MAX_SVG_ELEMENTS or depth > 8:
        return

    etype = entity.dxftype()

    if etype == "INSERT":
        _handle_insert(entity, elements, xs, ys, counter, depth, doc,
                        insert_positions=insert_positions)
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
    else:
        # Non-renderable entity types (ATTDEF, ATTRIB, SOLID, HATCH, DIMENSION, etc.)
        # Don't create SVG elements, but extract position for INSERT centroid tracking.
        # Critical for fire alarm symbol blocks that contain primarily ATTDEF entities.
        _extract_position(entity, xs, ys)


def _handle_insert(entity, elements: list, xs: list, ys: list,
                   counter: list, depth: int, doc,
                   insert_positions: dict | None = None):
    """Expand an INSERT entity into SVG elements.

    Strategy:
    1. Try ezdxf's virtual_entities() (handles all transforms automatically)
    2. If that fails, manually expand by reading the block definition and
       wrapping it in an SVG <g> with the INSERT's transform
    """
    expanded = False
    block_name = entity.dxf.name

    # Track geometry bounds for this specific INSERT to compute SVG position
    local_xs: list[float] = []
    local_ys: list[float] = []

    # Strategy 1: virtual_entities() — the official ezdxf way
    try:
        for ve in entity.virtual_entities():
            if counter[0] >= MAX_SVG_ELEMENTS:
                break
            try:
                _process_entity(ve, elements, local_xs, local_ys, counter, depth + 1, doc)
                expanded = True
            except Exception:
                continue
    except Exception:
        pass

    if expanded:
        # Add local bounds to global bounds
        xs.extend(local_xs)
        ys.extend(local_ys)
        # Record SVG-space position for this INSERT (depth 0 = top-level modelspace)
        if insert_positions is not None and depth == 0:
            if local_xs and local_ys:
                # Use centroid of expanded geometry
                cx = (min(local_xs) + max(local_xs)) / 2
                cy = (min(local_ys) + max(local_ys)) / 2
                insert_positions.setdefault(block_name, []).append((round(cx, 2), round(cy, 2)))
            else:
                # virtual_entities() "succeeded" but produced no geometry at all.
                # Use insertion point adjusted by block base_point to get correct
                # world-space position. DWG blocks often have large base_point offsets.
                _record_adjusted_insert_position(entity, block_name, doc, insert_positions)
        return

    # Strategy 2: Manual block definition expansion with SVG transform.
    # After DWG→DXF conversion, virtual_entities() often fails because block
    # definitions are incomplete or contain unsupported entity types. But the
    # basic geometry (lines, polylines, circles) is usually preserved.
    if doc is not None:
        try:
            block = doc.blocks.get(block_name)
            if block is not None and _block_has_renderable_content(block):
                expanded = _manual_expand_block(
                    entity, block, elements, xs, ys, counter, depth, doc
                )
                if expanded and insert_positions is not None and depth == 0:
                    # Use base_point-adjusted position (not raw insert point)
                    _record_adjusted_insert_position(entity, block_name, doc, insert_positions)
        except Exception:
            pass

    # Last resort: record insertion point for bounds calculation
    if not expanded:
        try:
            # Use base_point-adjusted position for correct world coordinates
            adj_x, adj_y = _get_adjusted_insert_position(entity, block_name, doc)
            xs.append(adj_x)
            ys.append(adj_y)
            if insert_positions is not None and depth == 0:
                insert_positions.setdefault(block_name, []).append(
                    (round(adj_x, 2), round(adj_y, 2)))
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
