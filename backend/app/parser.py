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


def parse_dxf_file(filepath: str) -> list[SymbolInfo]:
    """
    Parse a DXF file and count all block references (INSERT entities).

    This is the core accuracy engine. Scans ALL layouts (model space AND
    paper space), then recursively resolves nested block references to
    get accurate total counts.
    """
    try:
        doc = ezdxf.readfile(filepath)
    except ezdxf.DXFError as e:
        raise HTTPException(400, f"Invalid DXF file: {str(e)}")
    except Exception as e:
        raise HTTPException(400, f"Could not read DXF file: {str(e)}")

    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)

    # Phase 1: Scan ALL layouts (model space + all paper space layouts)
    # Many fire alarm drawings organize content in paper space layouts
    for layout in doc.layouts:
        for entity in layout:
            if entity.dxftype() == "INSERT":
                block_name = entity.dxf.name
                if _should_skip_block(block_name):
                    continue
                block_counts[block_name] += 1
                insert_point = entity.dxf.insert
                block_locations[block_name].append(
                    (round(insert_point.x, 2), round(insert_point.y, 2))
                )

    # Phase 2: Build nested reference map from block definitions
    # Count how many times each block definition INSERTs other blocks
    nested_ref_counts: dict[str, dict[str, int]] = {}
    for block in doc.blocks:
        if _should_skip_block(block.name):
            continue
        refs: dict[str, int] = defaultdict(int)
        for entity in block:
            if entity.dxftype() == "INSERT" and not _should_skip_block(entity.dxf.name):
                refs[entity.dxf.name] += 1
        if refs:
            nested_ref_counts[block.name] = dict(refs)

    # Phase 3: Propagate counts through nesting hierarchy (BFS)
    # If block A (count=N) contains M INSERTs of block B, then B gets N*M additional
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

    return symbols


def parse_dwg_file(filepath: str) -> list[SymbolInfo]:
    """
    Parse a DWG file by converting to DXF first, then parsing.

    DWG is AutoCAD's proprietary binary format. Conversion strategy:
    1. LibreDWG dwg2dxf (open source, installed in Docker image)
    2. ODA File Converter (if available on system)
    3. ezdxf recovery mode (limited, works for some files)
    """
    # Strategy 1: LibreDWG dwg2dxf (primary — fast, reliable, open source)
    dwg2dxf_path = _find_dwg2dxf()
    if dwg2dxf_path:
        try:
            return _convert_with_libredwg(filepath, dwg2dxf_path)
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to next strategy

    # Strategy 2: ODA File Converter
    oda_path = _find_oda_converter()
    if oda_path:
        try:
            return _convert_with_oda(filepath, oda_path)
        except HTTPException:
            raise
        except Exception:
            pass  # Fall through to next strategy

    # Strategy 3: ezdxf recovery mode (handles some DWG-like files)
    try:
        doc, auditor = ezdxf.recover.readfile(filepath)
        if auditor.has_errors:
            pass  # Partial data is better than none
    except Exception:
        pass
    else:
        temp_dxf = filepath + ".converted.dxf"
        try:
            doc.saveas(temp_dxf)
            return parse_dxf_file(temp_dxf)
        except Exception:
            pass
        finally:
            Path(temp_dxf).unlink(missing_ok=True)

    raise HTTPException(
        400,
        "Cannot parse this DWG file. No compatible converter is available. "
        "Please convert the file to DXF format using AutoCAD, BricsCAD, "
        "or a free tool like Autodesk's online viewer, then upload the DXF."
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


def _convert_with_libredwg(dwg_path: str, dwg2dxf_path: str) -> list[SymbolInfo]:
    """Convert DWG to DXF using LibreDWG's dwg2dxf, then parse."""
    with tempfile.TemporaryDirectory() as tmpdir:
        dxf_out = Path(tmpdir) / (Path(dwg_path).stem + ".dxf")
        try:
            result = subprocess.run(
                [dwg2dxf_path, "-y", "-o", str(dxf_out), dwg_path],
                timeout=120,
                capture_output=True,
                text=True,
            )
        except subprocess.TimeoutExpired:
            raise HTTPException(500, "DWG conversion timed out")
        except Exception as e:
            raise HTTPException(500, f"DWG conversion failed: {str(e)}")

        if not dxf_out.exists():
            # dwg2dxf may output to current directory without -o
            # Try alternate location
            alt_path = Path(dwg_path).with_suffix(".dxf")
            if alt_path.exists():
                return parse_dxf_file(str(alt_path))
            raise HTTPException(
                500,
                f"DWG conversion produced no output. "
                f"Converter stderr: {result.stderr[:200] if result.stderr else 'none'}"
            )

        return parse_dxf_file(str(dxf_out))


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


def _convert_with_oda(dwg_path: str, oda_path: str) -> list[SymbolInfo]:
    """Convert DWG to DXF using ODA File Converter, then parse."""
    dwg_file = Path(dwg_path)
    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                [
                    oda_path,
                    str(dwg_file.parent),  # input dir
                    tmpdir,                # output dir
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
            raise HTTPException(500, "DWG conversion timed out")
        except Exception as e:
            raise HTTPException(500, f"DWG conversion failed: {str(e)}")

        dxf_files = list(Path(tmpdir).glob("*.dxf"))
        if not dxf_files:
            raise HTTPException(500, "DWG conversion produced no output")

        return parse_dxf_file(str(dxf_files[0]))
