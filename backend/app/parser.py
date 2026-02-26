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

# Block names to always skip (AutoCAD internal blocks, dimensions, etc.)
SKIP_PATTERNS = [
    r"^\*",           # AutoCAD anonymous blocks (*D1, *U2, etc.)
    r"^_",            # Internal blocks
    r"^A\$C",         # AutoCAD system blocks
    r"^ACAD",         # AutoCAD system blocks
    r"^AcDb",         # AutoCAD database objects
    r"^DIMENSION",    # Dimension blocks
    r"^LEADER",       # Leader blocks
    r"^MTEXT",        # MText blocks
    r"^SOLID",        # Solid blocks
    r"^HATCH",        # Hatch patterns
    r"^VIEWPORT",     # Viewport blocks
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


def parse_dxf_file(filepath: str) -> list[SymbolInfo]:
    """
    Parse a DXF file and count all block references (INSERT entities).

    This is the core accuracy engine. Each INSERT entity in a DXF file
    represents one placed instance of a symbol (block). Counting INSERTs
    grouped by block name gives us exact symbol counts.
    """
    try:
        doc = ezdxf.readfile(filepath)
    except ezdxf.DXFError as e:
        raise HTTPException(400, f"Invalid DXF file: {str(e)}")
    except Exception as e:
        raise HTTPException(400, f"Could not read DXF file: {str(e)}")

    msp = doc.modelspace()

    # Count INSERT entities grouped by block name
    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)

    for entity in msp:
        if entity.dxftype() == "INSERT":
            block_name = entity.dxf.name
            if _should_skip_block(block_name):
                continue
            block_counts[block_name] += 1
            # Store first 5 insertion points as samples
            if len(block_locations[block_name]) < 5:
                insert_point = entity.dxf.insert
                block_locations[block_name].append(
                    (round(insert_point.x, 2), round(insert_point.y, 2))
                )

    # Also scan nested blocks (blocks within blocks)
    for block in doc.blocks:
        if _should_skip_block(block.name):
            continue
        for entity in block:
            if entity.dxftype() == "INSERT":
                nested_name = entity.dxf.name
                if _should_skip_block(nested_name):
                    continue
                # If the parent block is inserted N times, each nested insert
                # appears N times total. We track these separately.
                parent_count = block_counts.get(block.name, 0)
                if parent_count > 0:
                    block_counts[nested_name] += parent_count

    # Build result sorted by count (most frequent first)
    symbols = []
    for block_name, count in sorted(block_counts.items(), key=lambda x: -x[1]):
        symbols.append(
            SymbolInfo(
                block_name=block_name,
                label=_guess_label(block_name),
                count=count,
                sample_locations=block_locations.get(block_name, []),
            )
        )

    return symbols


def parse_dwg_file(filepath: str) -> list[SymbolInfo]:
    """
    Parse a DWG file by first converting to DXF, then parsing.

    DWG is AutoCAD's proprietary binary format. We convert it to DXF
    using the ODA File Converter (if available) or ezdxf's recovery mode.
    """
    # Try using ezdxf's recover mode which can handle some DWG-like files
    try:
        doc, auditor = ezdxf.recover.readfile(filepath)
        if auditor.has_errors:
            # Log but continue — partial data is better than none
            pass
    except Exception:
        pass
    else:
        # If ezdxf can read it directly, parse it
        temp_dxf = filepath + ".converted.dxf"
        try:
            doc.saveas(temp_dxf)
            return parse_dxf_file(temp_dxf)
        finally:
            Path(temp_dxf).unlink(missing_ok=True)

    # Try ODA File Converter if available
    oda_path = _find_oda_converter()
    if oda_path:
        return _convert_with_oda(filepath, oda_path)

    raise HTTPException(
        400,
        "Cannot parse DWG file. The ODA File Converter is not installed. "
        "Please convert the file to DXF format using AutoCAD or a free online converter, "
        "then upload the DXF file."
    )


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

    # Try to find it in PATH
    try:
        result = subprocess.run(
            ["which", "ODAFileConverter"],
            capture_output=True, text=True, timeout=5
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

        # Find the converted DXF file
        dxf_files = list(Path(tmpdir).glob("*.dxf"))
        if not dxf_files:
            raise HTTPException(500, "DWG conversion produced no output")

        return parse_dxf_file(str(dxf_files[0]))
