"""
DXF/DWG Parser — raw block scanner.

DXF files store reusable symbols as "blocks" (block definitions).
When a symbol is placed on a drawing, it creates an INSERT entity
that references the block by name, with a position (x, y, z).

APPROACH: Legend-first architecture. The parser is a pure scanner that
extracts ALL block references with metadata. No labeling, no classification.
The legend matching step (matching.py) handles identification and naming.
"""

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from fastapi import HTTPException

from app.models import AuditEntry, SymbolInfo

# Block names to always skip (truly internal AutoCAD objects)
SKIP_PATTERNS = [
    r"^\*Model_Space",
    r"^\*Paper_Space",
    r"^\*D\d+",
    r"^\*T\d+",
    r"^_",
    r"^A\$C",
    r"^AcDb",
    r"^ACAD_DSTYLE",
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
class BlockInfo:
    """All metadata about a block found in the drawing."""
    block_name: str
    count: int
    layers: list[str] = field(default_factory=list)
    entity_types: dict[str, int] = field(default_factory=dict)
    attribs: dict[str, str] = field(default_factory=dict)
    texts_inside: list[str] = field(default_factory=list)
    description: str = ""
    locations: list[tuple[float, float]] = field(default_factory=list)
    attdef_tags: dict[str, str] = field(default_factory=dict)


@dataclass
class ParseResult:
    """Internal result from parsing — raw blocks + analysis log."""
    symbols: list[SymbolInfo] = field(default_factory=list)
    analysis: list[dict] = field(default_factory=list)
    dxf_path: str = ""
    # All scanned blocks with metadata
    raw_blocks: list[BlockInfo] = field(default_factory=list)
    # Drawing-wide context
    all_block_names: list[str] = field(default_factory=list)
    all_layer_names: list[str] = field(default_factory=list)
    legend_texts: list[str] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
    xref_warnings: list[str] = field(default_factory=list)

    def log(self, type: str, message: str):
        self.analysis.append({"type": type, "message": message})


def _should_skip_block(block_name: str) -> bool:
    """Check if a block name is an AutoCAD system/internal block."""
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, block_name, re.IGNORECASE):
            return True
    return False


def _extract_legend_texts(doc) -> list[str]:
    """Extract text from the drawing that could be legend/schedule/symbol key info."""
    legend_texts = []
    legend_keywords = [
        "legend", "schedule", "symbol", "device", "key",
        "leyenda", "referencia", "simbologia",
        "smoke", "heat", "detector", "horn", "strobe", "pull",
        "alarm", "fire", "notification", "initiating",
    ]

    try:
        for layout in doc.layouts:
            for entity in layout:
                etype = entity.dxftype()
                text = ""
                if etype == "TEXT":
                    text = entity.dxf.text.strip()
                elif etype == "MTEXT":
                    try:
                        text = entity.plain_text().strip()
                    except Exception:
                        text = entity.text.strip() if hasattr(entity, 'text') and entity.text else ""

                if not text or len(text) < 3 or len(text) > 500:
                    continue

                text_lower = text.lower()
                if any(kw in text_lower for kw in legend_keywords):
                    legend_texts.append(text)

                    if len(legend_texts) >= 50:
                        return legend_texts
    except Exception:
        pass

    return legend_texts


def _collect_block_metadata(block_def, doc) -> dict:
    """Collect all metadata from a block definition."""
    texts_inside = []
    attdef_tags = {}
    description = ""
    entity_types: dict[str, int] = defaultdict(int)

    try:
        description = block_def.block.dxf.get("description", "") or ""
    except Exception:
        pass

    try:
        for attdef in block_def.attdefs():
            tag = attdef.dxf.tag.upper().strip()
            default_text = attdef.dxf.text.strip()
            if default_text:
                attdef_tags[tag] = default_text
    except Exception:
        pass

    try:
        for entity in block_def:
            etype = entity.dxftype()
            entity_types[etype] = entity_types.get(etype, 0) + 1
            if etype == "TEXT":
                t = entity.dxf.text.strip()
                if t and 1 <= len(t) <= 30:
                    texts_inside.append(t)
            elif etype == "MTEXT":
                try:
                    t = entity.plain_text().strip()
                except Exception:
                    t = ""
                if t and 1 <= len(t) <= 30:
                    texts_inside.append(t)
    except Exception:
        pass

    return {
        "description": description,
        "texts_inside": texts_inside[:10],
        "attdef_tags": attdef_tags,
        "entity_types": dict(entity_types),
    }


def parse_dxf_file(filepath: str) -> ParseResult:
    """Parse a DXF file and extract all block references with metadata.

    Returns raw blocks — no classification or labeling.
    The legend matching step handles identification.
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

    # Step 3: Analyze layers
    layer_names = []
    try:
        for layer in doc.layers:
            lname = layer.dxf.name
            layer_names.append(lname)
    except Exception:
        pass

    result.all_layer_names = layer_names

    if layer_names:
        result.log("info", f"Layers in drawing: {len(layer_names)} total")
        if len(layer_names) <= 20:
            result.log("info", f"Layer names: {', '.join(layer_names)}")
        else:
            result.log("info", f"Layer names (first 20): {', '.join(layer_names[:20])}...")

    # Step 4: Extract legend/schedule text for context
    legend_texts = _extract_legend_texts(doc)
    result.legend_texts = legend_texts
    if legend_texts:
        result.log("success", f"Found {len(legend_texts)} legend/schedule text elements")

    # Step 5: Enumerate layouts and scan all INSERT entities
    layout_names = [layout.name for layout in doc.layouts]
    result.log("info", f"Layouts found: {len(layout_names)} — {', '.join(layout_names)}")

    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    block_layers: dict[str, set[str]] = defaultdict(set)
    block_attribs: dict[str, dict[str, str]] = {}
    skipped_blocks: dict[str, int] = defaultdict(int)

    total_entities = 0
    total_inserts = 0

    for layout in doc.layouts:
        layout_entity_count = 0
        layout_insert_count = 0
        layout_types: dict[str, int] = defaultdict(int)
        is_model_space = layout.name == "Model"

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

                # Only count and collect data from model space.
                # Paper space contains legends, title blocks, and viewports —
                # not real device placements.
                if not is_model_space:
                    continue

                block_counts[block_name] += 1

                try:
                    block_layers[block_name].add(entity.dxf.layer)
                except Exception:
                    pass

                try:
                    if hasattr(entity, "attribs") and entity.attribs:
                        for attrib in entity.attribs:
                            tag = attrib.dxf.tag.upper().strip()
                            value = attrib.dxf.text.strip()
                            if value and block_name not in block_attribs:
                                block_attribs[block_name] = {}
                            if value:
                                block_attribs[block_name][tag] = value
                except Exception:
                    pass

                try:
                    insert_point = entity.dxf.insert
                    block_locations[block_name].append(
                        (round(insert_point.x, 2), round(insert_point.y, 2))
                    )
                except Exception:
                    pass

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

    # Step 6: Analyze block definitions — nested refs + metadata
    nested_ref_counts: dict[str, dict[str, int]] = {}
    block_def_metadata: dict[str, dict] = {}

    for block in doc.blocks:
        if _should_skip_block(block.name):
            continue
        refs: dict[str, int] = defaultdict(int)
        for entity in block:
            if entity.dxftype() == "INSERT" and not _should_skip_block(entity.dxf.name):
                refs[entity.dxf.name] += 1
        if refs:
            nested_ref_counts[block.name] = dict(refs)

        if block.name in block_counts:
            block_def_metadata[block.name] = _collect_block_metadata(block, doc)

    # Step 7: Propagate counts through nesting hierarchy (BFS)
    directly_inserted = set(block_counts.keys())
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
            if child in directly_inserted:
                block_counts[child] += parent_count * ref_count

    changed = [
        f"{k}: {pre_bfs.get(k, 0)} -> {v}"
        for k, v in block_counts.items()
        if v != pre_bfs.get(k, 0)
    ]
    if changed:
        result.log("info", f"Nesting resolved: {', '.join(changed[:8])}")

    # Step 8: Detect XREFs (external references)
    try:
        for block in doc.blocks:
            if hasattr(block, 'is_xref') and block.is_xref:
                result.xref_warnings.append(
                    f"External reference (XREF) detected: \"{block.name}\" — "
                    "devices in XREFs are not counted. Resolve XREFs in AutoCAD "
                    "and re-export for complete counts."
                )
            elif hasattr(block, 'block') and hasattr(block.block, 'dxf'):
                flags = block.block.dxf.get('flags', 0)
                if flags & 4:  # Bit 2 = XREF
                    result.xref_warnings.append(
                        f"External reference (XREF) detected: \"{block.name}\" — "
                        "devices in XREFs are not counted."
                    )
    except Exception:
        pass

    if result.xref_warnings:
        result.log("warning", f"{len(result.xref_warnings)} external references (XREFs) detected — devices in referenced files are not counted")

    # Step 9: Collect all blocks as raw entries — no classification
    result.all_block_names = sorted(block_counts.keys())

    for block_name, count in sorted(block_counts.items(), key=lambda x: -x[1]):
        layers = sorted(block_layers.get(block_name, set()))
        meta = block_def_metadata.get(block_name, {})

        result.raw_blocks.append(BlockInfo(
            block_name=block_name,
            count=count,
            layers=layers,
            entity_types=meta.get("entity_types", {}),
            attribs=block_attribs.get(block_name, {}),
            texts_inside=meta.get("texts_inside", []),
            description=meta.get("description", ""),
            locations=block_locations.get(block_name, []),
            attdef_tags=meta.get("attdef_tags", {}),
        ))

    total = sum(b.count for b in result.raw_blocks)
    result.log("success", f"Scan complete: {len(result.raw_blocks)} unique blocks, {total} total insertions")

    return result


def _merge_dxf_result(result: ParseResult, dxf_result: ParseResult, dxf_path: str):
    """Copy all parse data from a DXF parse into the DWG result."""
    result.analysis.extend(dxf_result.analysis)
    result.symbols = dxf_result.symbols
    result.raw_blocks = dxf_result.raw_blocks
    result.all_block_names = dxf_result.all_block_names
    result.all_layer_names = dxf_result.all_layer_names
    result.legend_texts = dxf_result.legend_texts
    result.audit = dxf_result.audit
    result.xref_warnings = dxf_result.xref_warnings
    result.dxf_path = dxf_path


def parse_dwg_file(filepath: str) -> ParseResult:
    """Parse a DWG file by converting to DXF first, then parsing."""
    result = ParseResult()
    file_size_mb = Path(filepath).stat().st_size / (1024 * 1024)
    result.log("info", f"File type: DWG (binary AutoCAD format, {file_size_mb:.1f} MB)")
    result.log("info", "DWG files require conversion to DXF before analysis")
    result.log(
        "warning",
        "DWG conversion may lose data (dynamic block names, some entities). "
        "For best results, export DXF directly from AutoCAD or BricsCAD."
    )

    # Strategy 1: ODA File Converter (preferred — better fidelity for modern DWG)
    oda_path = _find_oda_converter()
    if oda_path:
        result.log("info", f"Using ODA File Converter: {oda_path}")
        try:
            dxf_path = _convert_with_oda(filepath, oda_path, result)
            _merge_dxf_result(result, parse_dxf_file(dxf_path), dxf_path)
            return result
        except HTTPException:
            raise
        except Exception as e:
            result.log("error", f"ODA conversion failed: {str(e)}")
    else:
        result.log("info", "ODA File Converter not available")

    # Strategy 2: LibreDWG dwg2dxf (fallback — open source, less reliable for 2018+)
    dwg2dxf_path = _find_dwg2dxf()
    if dwg2dxf_path:
        result.log("info", f"Using LibreDWG converter: {dwg2dxf_path}")
        try:
            dxf_path = _convert_with_libredwg(filepath, dwg2dxf_path, result)
            _merge_dxf_result(result, parse_dxf_file(dxf_path), dxf_path)
            return result
        except HTTPException:
            raise
        except Exception as e:
            result.log("error", f"LibreDWG conversion failed: {str(e)}")
    else:
        result.log("warning", "LibreDWG converter not found on system")

    # Strategy 3: ezdxf recovery mode (last resort)
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

    dxf_path = filepath + ".recovered.dxf"
    try:
        doc.saveas(dxf_path)
        result.log("success", f"Saved recovered DXF ({Path(dxf_path).stat().st_size / 1024:.0f} KB)")
        _merge_dxf_result(result, parse_dxf_file(dxf_path), dxf_path)
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
        r = subprocess.run(
            ["which", "dwg2dxf"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _convert_with_libredwg(
    dwg_path: str, dwg2dxf_path: str, result: ParseResult
) -> str:
    """Convert DWG to DXF using LibreDWG's dwg2dxf."""
    dxf_out = Path(dwg_path).with_suffix(".converted.dxf")
    result.log("info", "Converting DWG to DXF...")

    try:
        proc = subprocess.run(
            [dwg2dxf_path, "-y", "-o", str(dxf_out), dwg_path],
            timeout=120, capture_output=True, text=True,
        )
    except subprocess.TimeoutExpired:
        result.log("error", "Conversion timed out after 120 seconds")
        raise HTTPException(500, "DWG conversion timed out")
    except Exception as e:
        result.log("error", f"Conversion error: {str(e)}")
        raise HTTPException(500, f"DWG conversion failed: {str(e)}")

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
    for p in [
        "/usr/bin/ODAFileConverter",
        "/usr/local/bin/ODAFileConverter",
        "/opt/ODAFileConverter/ODAFileConverter",
    ]:
        if Path(p).exists():
            return p
    try:
        r = subprocess.run(
            ["which", "ODAFileConverter"], capture_output=True, text=True, timeout=5
        )
        if r.returncode == 0:
            return r.stdout.strip()
    except Exception:
        pass
    return None


def _convert_with_oda(
    dwg_path: str, oda_path: str, result: ParseResult
) -> str:
    """Convert DWG to DXF using ODA File Converter."""
    dwg_file = Path(dwg_path)
    output_dir = dwg_file.parent
    result.log("info", "Converting DWG to DXF with ODA...")

    try:
        subprocess.run(
            [
                oda_path,
                str(dwg_file.parent), str(output_dir),
                "ACAD2018", "DXF", "0", "1", dwg_file.name,
            ],
            timeout=120, capture_output=True,
        )
    except subprocess.TimeoutExpired:
        result.log("error", "ODA conversion timed out after 120 seconds")
        raise HTTPException(500, "DWG conversion timed out")
    except Exception as e:
        result.log("error", f"ODA conversion error: {str(e)}")
        raise HTTPException(500, f"DWG conversion failed: {str(e)}")

    dxf_path = output_dir / dwg_file.with_suffix(".dxf").name
    if not dxf_path.exists():
        dxf_files = list(output_dir.glob("*.dxf"))
        if dxf_files:
            dxf_path = dxf_files[0]
        else:
            result.log("error", "ODA conversion produced no output file")
            raise HTTPException(500, "DWG conversion produced no output")

    size_kb = dxf_path.stat().st_size / 1024
    result.log("success", f"ODA conversion complete: {dxf_path.name} ({size_kb:.0f} KB)")
    return str(dxf_path)
