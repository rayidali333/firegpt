"""
DXF/DWG Parser — Core symbol detection engine.

DXF files store reusable symbols as "blocks" (block definitions).
When a symbol is placed on a drawing, it creates an INSERT entity
that references the block by name, with a position (x, y, z).

For fire alarm drawings, symbols like SD (Smoke Detector), HD (Heat Detector),
PS (Pull Station) are stored as named blocks. We count INSERT references
to each block to get accurate symbol counts.
"""

import re
import subprocess
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from fastapi import HTTPException

from app.models import SymbolInfo

# Common fire alarm symbol patterns for auto-labeling
KNOWN_SYMBOLS = {
    "SD": "Smoke Detector",
    "HD": "Heat Detector",
    "PS": "Pull Station",
    "NAC": "Notification Appliance Circuit",
    "HS": "Horn/Strobe",
    "HORN": "Horn",
    "STROBE": "Strobe",
    "H/S": "Horn/Strobe",
    "FACP": "Fire Alarm Control Panel",
    "ANN": "Annunciator",
    "DUCT": "Duct Detector",
    "DD": "Duct Detector",
    "BG": "Break Glass",
    "MCP": "Manual Call Point",
    "FD": "Fire Door Holder",
    "SPK": "Sprinkler",
    "SPKR": "Speaker",
    "PIV": "Post Indicator Valve",
    "FDC": "Fire Department Connection",
    "OS/Y": "OS&Y Valve",
    "BEAM": "Beam Detector",
    "VESDA": "VESDA Detector",
    "MODULE": "Monitor/Control Module",
    "MON": "Monitor Module",
    "CM": "Control Module",
    "REL": "Relay Module",
    "EOL": "End of Line",
    "SLC": "Signaling Line Circuit",
    "TB": "Terminal Box",
    "JB": "Junction Box",
    "WP": "Weatherproof",
}

# Color assignments by symbol category for drawing visualization
SYMBOL_COLORS: dict[str, str] = {
    "Smoke Detector": "#E74C3C",
    "Heat Detector": "#E67E22",
    "Duct Detector": "#D35400",
    "Beam Detector": "#C0392B",
    "VESDA Detector": "#922B21",
    "Pull Station": "#F39C12",
    "Break Glass": "#F1C40F",
    "Manual Call Point": "#F39C12",
    "Horn/Strobe": "#3498DB",
    "Horn": "#2980B9",
    "Strobe": "#1ABC9C",
    "Speaker": "#2ECC71",
    "Notification Appliance Circuit": "#3498DB",
    "Fire Alarm Control Panel": "#9B59B6",
    "Annunciator": "#8E44AD",
    "Monitor Module": "#27AE60",
    "Control Module": "#16A085",
    "Monitor/Control Module": "#1ABC9C",
    "Relay Module": "#2C3E50",
    "End of Line": "#7F8C8D",
    "Signaling Line Circuit": "#34495E",
    "Fire Door Holder": "#795548",
    "Sprinkler": "#607D8B",
    "Post Indicator Valve": "#546E7A",
    "Fire Department Connection": "#455A64",
    "OS&Y Valve": "#546E7A",
    "Terminal Box": "#7F8C8D",
    "Junction Box": "#95A5A6",
    "Weatherproof": "#607D8B",
}

DEFAULT_COLOR = "#95A5A6"

# Block names to always skip (only truly internal AutoCAD objects)
# NOTE: We do NOT skip all *-prefixed blocks — anonymous blocks (*U1, *X1)
# can contain valid dynamic block content in fire alarm drawings.
SKIP_PATTERNS = [
    r"^\*Model_Space",    # Model space container
    r"^\*Paper_Space",    # Paper space containers
    r"^\*D\d+",           # Dimension blocks (*D1, *D2, ...)
    r"^\*T\d+",           # Table blocks
    r"^_",                # Internal blocks
    r"^A\$C",             # AutoCAD system blocks
    r"^AcDb",             # AutoCAD database objects
    r"^ACAD_DSTYLE",      # Dimension style overrides
]

# DXF version codes to human-readable names
DXF_VERSIONS = {
    "AC1009": "AutoCAD R12",
    "AC1012": "AutoCAD R13",
    "AC1014": "AutoCAD R14",
    "AC1015": "AutoCAD 2000",
    "AC1018": "AutoCAD 2004",
    "AC1021": "AutoCAD 2007",
    "AC1024": "AutoCAD 2010",
    "AC1027": "AutoCAD 2013",
    "AC1032": "AutoCAD 2018+",
}


@dataclass
class ParseResult:
    """Internal result from parsing, includes symbols + analysis log + file path."""
    symbols: list[SymbolInfo] = field(default_factory=list)
    analysis: list[dict] = field(default_factory=list)
    dxf_path: str = ""  # Actual DXF file path (for preview generation)

    def log(self, type: str, message: str):
        self.analysis.append({"type": type, "message": message})


def _should_skip_block(block_name: str) -> bool:
    """Check if a block name is an AutoCAD system/internal block."""
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, block_name, re.IGNORECASE):
            return True
    return False


def _guess_label(block_name: str) -> str:
    """Try to match a block name to a known fire alarm symbol."""
    name_upper = block_name.upper().strip()

    # Direct match
    if name_upper in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[name_upper]

    # Check if known symbol is contained in the block name
    for abbrev, label in KNOWN_SYMBOLS.items():
        if abbrev in name_upper:
            return label

    # Clean up the block name for display
    cleaned = block_name.replace("_", " ").replace("-", " ").strip()
    return cleaned


def _get_symbol_color(label: str) -> str:
    """Get the visualization color for a symbol based on its label."""
    return SYMBOL_COLORS.get(label, DEFAULT_COLOR)


def parse_dxf_file(filepath: str) -> ParseResult:
    """
    Parse a DXF file and count all block references (INSERT entities).

    Returns a ParseResult with symbols, step-by-step analysis log, and
    the effective DXF file path for preview generation.
    """
    result = ParseResult(dxf_path=filepath)

    # Step 1: Open DXF file
    try:
        doc = ezdxf.readfile(filepath)
        result.log("success", "Opened DXF file successfully")
    except ezdxf.DXFError:
        try:
            doc, auditor = ezdxf.recover.readfile(filepath)
            n_errors = len(auditor.errors) if auditor.errors else 0
            result.log("warning", f"Opened with recovery mode ({n_errors} issues found)")
        except Exception as e:
            result.log("error", f"Cannot read file: {str(e)}")
            raise HTTPException(400, f"Invalid DXF file: {str(e)}")
    except Exception as e:
        result.log("error", f"Cannot read file: {str(e)}")
        raise HTTPException(400, f"Could not read DXF file: {str(e)}")

    # Step 2: Log DXF metadata
    version_code = doc.dxfversion
    version_name = DXF_VERSIONS.get(version_code, version_code)
    result.log("info", f"DXF version: {version_code} ({version_name})")

    # Step 3: Enumerate layouts
    layout_names = [layout.name for layout in doc.layouts]
    result.log("info", f"Layouts found: {len(layout_names)} — {', '.join(layout_names)}")

    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    skipped_blocks: dict[str, int] = defaultdict(int)

    # Phase 1: Scan ALL layouts (model space + all paper space layouts)
    total_entities = 0
    total_inserts = 0

    for layout in doc.layouts:
        layout_entity_count = 0
        layout_insert_count = 0
        layout_types: dict[str, int] = defaultdict(int)

        for entity in layout:
            total_entities += 1
            layout_entity_count += 1
            etype = entity.dxftype()
            layout_types[etype] += 1

            if etype == "INSERT":
                block_name = entity.dxf.name
                total_inserts += 1
                layout_insert_count += 1

                if _should_skip_block(block_name):
                    skipped_blocks[block_name] += 1
                    continue

                block_counts[block_name] += 1
                try:
                    insert_point = entity.dxf.insert
                    block_locations[block_name].append(
                        (round(insert_point.x, 2), round(insert_point.y, 2))
                    )
                except Exception:
                    pass

        # Log per-layout stats
        top_types = sorted(layout_types.items(), key=lambda x: -x[1])[:8]
        types_str = ", ".join(f"{t}: {c}" for t, c in top_types)
        result.log(
            "info",
            f'Layout "{layout.name}": {layout_entity_count} entities'
            + (f" ({types_str})" if types_str else "")
        )

    result.log("info", f"Total entities scanned: {total_entities}")
    result.log(
        "info",
        f"INSERT references found: {total_inserts} total, "
        f"{len(block_counts)} unique blocks kept"
    )

    if skipped_blocks:
        skip_list = ", ".join(
            f"{n} ({c})" for n, c in sorted(skipped_blocks.items())[:10]
        )
        result.log("info", f"Skipped system blocks: {skip_list}")

    # Phase 2: Build nested reference map from block definitions
    nested_ref_counts: dict[str, dict[str, int]] = {}
    block_def_count = 0

    for block in doc.blocks:
        if _should_skip_block(block.name):
            continue
        block_def_count += 1
        refs: dict[str, int] = defaultdict(int)
        for entity in block:
            if entity.dxftype() == "INSERT" and not _should_skip_block(entity.dxf.name):
                refs[entity.dxf.name] += 1
        if refs:
            nested_ref_counts[block.name] = dict(refs)

    result.log("info", f"Block definitions analyzed: {block_def_count}")

    if nested_ref_counts:
        nesting_details = []
        for parent, children in list(nested_ref_counts.items())[:8]:
            child_str = ", ".join(f"{c}x {n}" for n, c in children.items())
            nesting_details.append(f'"{parent}" contains [{child_str}]')
        result.log("info", f"Nested blocks: {'; '.join(nesting_details)}")

    # Phase 3: Propagate counts through nesting hierarchy (BFS)
    pre_bfs = dict(block_counts)
    processed: set[str] = set()
    queue = list(block_counts.keys())
    while queue:
        parent = queue.pop(0)
        if parent in processed:
            continue
        processed.add(parent)
        if parent not in nested_ref_counts:
            continue
        parent_count = block_counts[parent]
        for child, ref_count in nested_ref_counts[parent].items():
            block_counts[child] += parent_count * ref_count
            if child not in processed:
                queue.append(child)

    # Log nesting changes
    changed = [
        f"{k}: {pre_bfs.get(k, 0)} -> {v}"
        for k, v in block_counts.items()
        if v != pre_bfs.get(k, 0)
    ]
    if changed:
        result.log("info", f"Nesting resolved: {', '.join(changed[:8])}")

    # Build result sorted by count (most frequent first)
    symbols = []
    for block_name, count in sorted(block_counts.items(), key=lambda x: -x[1]):
        label = _guess_label(block_name)
        symbols.append(
            SymbolInfo(
                block_name=block_name,
                label=label,
                count=count,
                locations=block_locations.get(block_name, []),
                color=_get_symbol_color(label),
            )
        )

    result.symbols = symbols
    total = sum(s.count for s in symbols)
    result.log("success", f"Detection complete: {len(symbols)} symbol types, {total} total devices")

    if total == 0:
        result.log(
            "warning",
            "No symbols detected. The drawing may use non-standard block names, "
            "or content may be in an unsupported format."
        )
    elif len(symbols) < 3 and total < 10:
        result.log(
            "warning",
            "Very few symbols detected. If you expected more, the DWG-to-DXF "
            "conversion may have lost data. Try exporting DXF directly from "
            "AutoCAD or BricsCAD for best results."
        )

    return result


def parse_dwg_file(filepath: str) -> ParseResult:
    """
    Parse a DWG file by converting to DXF first, then parsing.

    DWG is AutoCAD's proprietary binary format. Conversion strategy:
    1. LibreDWG dwg2dxf (open source, installed in Docker image)
    2. ODA File Converter (if available on system)
    3. ezdxf recovery mode (limited, works for some files)

    The converted DXF is saved alongside the DWG file so the preview
    generator can use it later (not in a temp directory).
    """
    result = ParseResult()
    file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
    result.log("info", f"File type: DWG (binary AutoCAD format, {file_size_mb:.1f} MB)")
    result.log("info", "DWG files require conversion to DXF before analysis")

    # Strategy 1: LibreDWG dwg2dxf (primary — fast, reliable, open source)
    dwg2dxf_path = _find_dwg2dxf()
    if dwg2dxf_path:
        result.log("info", f"Using LibreDWG converter: {dwg2dxf_path}")
        try:
            dxf_path = _convert_with_libredwg(filepath, dwg2dxf_path, result)
            dxf_result = parse_dxf_file(dxf_path)
            # Merge: DWG analysis first, then DXF analysis
            result.analysis.extend(dxf_result.analysis)
            result.symbols = dxf_result.symbols
            result.dxf_path = dxf_path
            return result
        except HTTPException:
            raise
        except Exception as e:
            result.log("error", f"LibreDWG conversion failed: {str(e)}")
    else:
        result.log("warning", "LibreDWG converter not found on system")

    # Strategy 2: ODA File Converter
    oda_path = _find_oda_converter()
    if oda_path:
        result.log("info", f"Using ODA File Converter: {oda_path}")
        try:
            dxf_path = _convert_with_oda(filepath, oda_path, result)
            dxf_result = parse_dxf_file(dxf_path)
            result.analysis.extend(dxf_result.analysis)
            result.symbols = dxf_result.symbols
            result.dxf_path = dxf_path
            return result
        except HTTPException:
            raise
        except Exception as e:
            result.log("error", f"ODA conversion failed: {str(e)}")
    else:
        result.log("info", "ODA File Converter not available")

    # Strategy 3: ezdxf recovery mode (handles some DWG-like files)
    result.log("info", "Attempting ezdxf recovery mode (last resort)...")
    try:
        doc, auditor = ezdxf.recover.readfile(filepath)
        n_errors = len(auditor.errors) if auditor.errors else 0
        result.log("warning", f"Recovery mode: {n_errors} issues found")
    except Exception as e:
        result.log("error", f"Recovery mode failed: {str(e)}")
        raise HTTPException(
            400,
            "Cannot parse this DWG file. No compatible converter produced usable output. "
            "Please convert the file to DXF format using AutoCAD, BricsCAD, "
            "or a free tool like Autodesk's online viewer, then upload the DXF."
        )

    # Save the recovered document as DXF for preview
    dxf_path = filepath + ".recovered.dxf"
    try:
        doc.saveas(dxf_path)
        result.log("success", f"Saved recovered DXF ({Path(dxf_path).stat().st_size / 1024:.0f} KB)")
        dxf_result = parse_dxf_file(dxf_path)
        result.analysis.extend(dxf_result.analysis)
        result.symbols = dxf_result.symbols
        result.dxf_path = dxf_path
        return result
    except Exception as e:
        result.log("error", f"Could not save recovered file: {str(e)}")
        raise HTTPException(
            400,
            "Cannot parse this DWG file. Recovery mode could not produce usable output. "
            "Please export the file as DXF from AutoCAD or BricsCAD."
        )


def _find_dwg2dxf() -> str | None:
    """Find the dwg2dxf binary from LibreDWG."""
    for p in ["/usr/local/bin/dwg2dxf", "/usr/bin/dwg2dxf"]:
        if Path(p).exists():
            return p
    try:
        result = subprocess.run(
            ["which", "dwg2dxf"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _convert_with_libredwg(
    dwg_path: str, dwg2dxf_path: str, result: ParseResult
) -> str:
    """Convert DWG to DXF using LibreDWG's dwg2dxf.

    Saves the converted DXF alongside the original DWG (persistent, not temp)
    so the preview generator can use it later.
    Returns path to the converted DXF file.
    """
    dxf_out = Path(dwg_path).with_suffix(".converted.dxf")
    result.log("info", "Converting DWG to DXF...")

    try:
        proc = subprocess.run(
            [dwg2dxf_path, "-y", "-o", str(dxf_out), dwg_path],
            timeout=120,
            capture_output=True,
            text=True,
        )
    except subprocess.TimeoutExpired:
        result.log("error", "Conversion timed out after 120 seconds")
        raise HTTPException(500, "DWG conversion timed out")
    except Exception as e:
        result.log("error", f"Conversion error: {str(e)}")
        raise HTTPException(500, f"DWG conversion failed: {str(e)}")

    # Log converter output (stderr often has useful info about what was processed)
    if proc.stderr:
        for line in proc.stderr.strip().split("\n")[:8]:
            line = line.strip()
            if line:
                result.log("info", f"dwg2dxf: {line}")
    if proc.stdout:
        for line in proc.stdout.strip().split("\n")[:5]:
            line = line.strip()
            if line:
                result.log("info", f"dwg2dxf: {line}")

    if not dxf_out.exists():
        # dwg2dxf sometimes writes to the same directory as input without -o
        alt_path = Path(dwg_path).with_suffix(".dxf")
        if alt_path.exists():
            size_kb = alt_path.stat().st_size / 1024
            result.log("success", f"Conversion complete: {alt_path.name} ({size_kb:.0f} KB)")
            return str(alt_path)
        result.log("error", "Conversion produced no output file")
        raise HTTPException(
            500,
            f"DWG conversion produced no output. "
            f"stderr: {proc.stderr[:300] if proc.stderr else 'none'}"
        )

    size_kb = dxf_out.stat().st_size / 1024
    result.log("success", f"Conversion complete: {dxf_out.name} ({size_kb:.0f} KB)")

    if size_kb < 1:
        result.log("warning", "Converted file is very small — data may have been lost")

    return str(dxf_out)


def _find_oda_converter() -> str | None:
    """Look for ODA File Converter on the system."""
    possible_paths = [
        "/usr/bin/ODAFileConverter",
        "/usr/local/bin/ODAFileConverter",
        "/opt/ODAFileConverter/ODAFileConverter",
    ]
    for p in possible_paths:
        if Path(p).exists():
            return p
    try:
        result = subprocess.run(
            ["which", "ODAFileConverter"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


def _convert_with_oda(
    dwg_path: str, oda_path: str, result: ParseResult
) -> str:
    """Convert DWG to DXF using ODA File Converter.

    Saves persistently for preview access. Returns path to converted DXF.
    """
    dwg_file = Path(dwg_path)
    output_dir = dwg_file.parent
    result.log("info", "Converting DWG to DXF with ODA...")

    try:
        subprocess.run(
            [
                oda_path,
                str(dwg_file.parent),  # input dir
                str(output_dir),       # output dir (same as input)
                "ACAD2018",            # output version
                "DXF",                 # output format
                "0",                   # recurse
                "1",                   # audit
                dwg_file.name,         # input filename filter
            ],
            timeout=120,
            capture_output=True,
        )
    except subprocess.TimeoutExpired:
        result.log("error", "ODA conversion timed out after 120 seconds")
        raise HTTPException(500, "DWG conversion timed out")
    except Exception as e:
        result.log("error", f"ODA conversion error: {str(e)}")
        raise HTTPException(500, f"DWG conversion failed: {str(e)}")

    # Look for the output DXF
    dxf_path = output_dir / dwg_file.with_suffix(".dxf").name
    if not dxf_path.exists():
        # Try glob for any new DXF files
        dxf_files = list(output_dir.glob("*.dxf"))
        if dxf_files:
            dxf_path = dxf_files[0]
        else:
            result.log("error", "ODA conversion produced no output file")
            raise HTTPException(500, "DWG conversion produced no output")

    size_kb = dxf_path.stat().st_size / 1024
    result.log("success", f"ODA conversion complete: {dxf_path.name} ({size_kb:.0f} KB)")
    return str(dxf_path)
