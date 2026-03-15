"""
DXF/DWG Parser — AI-first symbol detection engine.

DXF files store reusable symbols as "blocks" (block definitions).
When a symbol is placed on a drawing, it creates an INSERT entity
that references the block by name, with a position (x, y, z).

APPROACH: Dictionary matching is used only as a fast path for obvious
symbols (e.g., "SD", "SMOKE_DETECTOR"). All other blocks are sent to
Claude for AI classification with full drawing context — block names,
layers, attributes, internal text, geometry, and any legend/schedule
text found in the drawing. This makes detection robust across any
naming convention, language, or CAD standard.
"""

import logging
import math
import re
import subprocess
from collections import defaultdict

logger = logging.getLogger("firegpt.parser")
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from fastapi import HTTPException

from app.models import AuditEntry, SymbolInfo

# ────────────────────────────────────────────────────────
# Fast-path dictionary: only high-confidence exact matches
# ────────────────────────────────────────────────────────

# These are universally standard abbreviations that don't need AI.
# Anything ambiguous should go to AI for classification.
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
    "SPK": "Speaker",
    "SPKR": "Speaker",
    "SPEAKER": "Speaker",
    "LOUDSPEAKER": "Speaker",
    "SIREN": "Alarm Siren",
    "ALARM SIREN": "Alarm Siren",
    "SPRINKLER": "Sprinkler",
    "SPRK": "Sprinkler",
    "SPKL": "Sprinkler",
    "PIV": "Post Indicator Valve",
    "FDC": "Fire Department Connection",
    "OS/Y": "OS&Y Valve",
    "BEAM": "Beam Detector",
    "VESDA": "VESDA Detector",
    "ASD": "Aspirating Smoke Detector",
    "MODULE": "Monitor/Control Module",
    "MONITOR MODULE": "Monitor Module",
    "CONTROL MODULE": "Control Module",
    "MON": "Monitor Module",
    "CM": "Control Module",
    "REL": "Relay Module",
    "EOL": "End of Line",
    "SLC": "Signaling Line Circuit",
    "TB": "Terminal Box",
    "JB": "Junction Box",
    "WP": "Weatherproof",
}

# International terms — substring matched against normalized block names
KNOWN_SYMBOLS_INTL = {
    # Spanish
    "DETECTOR DE HUMO": "Smoke Detector",
    "DETECTOR DE CALOR": "Heat Detector",
    "DETECTOR DE INCENDIO": "Fire Detector",
    "DETECTOR TERMICO": "Heat Detector",
    "DETECTOR OPTICO": "Smoke Detector",
    "DETECTOR IONICO": "Smoke Detector",
    "DETECTOR TERMOVELOCIMETRICO": "Heat Detector",
    "DETECTOR LINEAL": "Beam Detector",
    "PULSADOR DE ALARMA": "Pull Station",
    "PULSADOR MANUAL": "Pull Station",
    "PULSADOR": "Pull Station",
    "LUZ DE EMERGENCIA": "Emergency Light",
    "LUMINARIA EMERGENCIA": "Emergency Light",
    "SALIDA DE EMERGENCIA": "Emergency Exit Sign",
    "CARTEL DE SALIDA": "Exit Sign",
    "MATAFUEGOS": "Fire Extinguisher",
    "EXTINTOR": "Fire Extinguisher",
    "SIRENA": "Horn/Strobe",
    "ALARMA SONORA": "Horn",
    "ALARMA VISUAL": "Strobe",
    "ALARMA": "Alarm Device",
    "TABLERO DE INCENDIO": "Fire Alarm Control Panel",
    "TABLERO DE BOMBEROS": "Fire Brigade Panel",
    "PANEL DE ALARMA": "Fire Alarm Control Panel",
    "TABLERO": "Fire Panel",
    "CENTRAL DE ALARMA": "Fire Alarm Control Panel",
    "ROCIADOR": "Sprinkler",
    "GABINETE DE INCENDIO": "Fire Cabinet",
    "GABINETE": "Fire Cabinet",
    "BOCA DE INCENDIO": "Fire Hydrant",
    "B.I.E.": "Fire Hydrant (BIE)",
    "BIE": "Fire Hydrant (BIE)",
    "HIDRANTE": "Fire Hydrant",
    "COLUMNA DE INCENDIO": "Fire Standpipe",
    "COLUMNA": "Fire Standpipe",
    "BOMBA DE INCENDIO": "Fire Pump",
    "BOMBA": "Fire Pump",
    "TOMA DE BOMBEROS": "Fire Department Connection",
    "TOMA IMPULSION": "Fire Department Connection",
    "CANERIA PRESURIZADA": "Pressurized Pipe",
    "CANERIA AEREA": "Overhead Pipe",
    "CANERIA": "Fire Pipe",
    "BOTIQUIN": "First Aid Kit",
    "VIA DE EVACUACION": "Evacuation Route",
    "EVACUACION": "Evacuation Route",
    "LLAVE DE CORTE": "Gas Shutoff Valve",
    "MODULO MONITOR": "Monitor Module",
    "MODULO CONTROL": "Control Module",
    "MODULO": "Module",
    # Portuguese
    "DETECTOR DE FUMACA": "Smoke Detector",
    "DETECTOR DE FUMACO": "Smoke Detector",
    "ACIONADOR MANUAL": "Pull Station",
    "BOTOEIRA": "Pull Station",
    "AVISADOR SONORO": "Horn",
    "SINALIZADOR VISUAL": "Strobe",
    "SAIDA DE EMERGENCIA": "Emergency Exit Sign",
    "EXTINTOR DE INCENDIO": "Fire Extinguisher",
    "MANGUEIRA": "Fire Hose",
    "CENTRAL DE INCENDIO": "Fire Alarm Control Panel",
    # French
    "DETECTEUR DE FUMEE": "Smoke Detector",
    "DETECTEUR DE CHALEUR": "Heat Detector",
    "DETECTEUR OPTIQUE": "Smoke Detector",
    "DETECTEUR": "Detector",
    "DECLENCHEUR MANUEL": "Pull Station",
    "EXTINCTEUR": "Fire Extinguisher",
    "SORTIE DE SECOURS": "Emergency Exit Sign",
    "ALARME INCENDIE": "Fire Alarm",
    "SIRENE": "Horn",
    "FLASH": "Strobe",
    "ROBINET INCENDIE": "Fire Hydrant",
    "COLONNE SECHE": "Fire Standpipe",
    "SPRINKLEUR": "Sprinkler",
    # Italian
    "RILEVATORE DI FUMO": "Smoke Detector",
    "RILEVATORE DI CALORE": "Heat Detector",
    "RILEVATORE": "Detector",
    "PULSANTE": "Pull Station",
    "ESTINTORE": "Fire Extinguisher",
    "USCITA DI EMERGENZA": "Emergency Exit Sign",
    "IDRANTE": "Fire Hydrant",
}

# Color assignments by symbol category for drawing visualization
SYMBOL_COLORS: dict[str, str] = {
    "Smoke Detector": "#E74C3C",
    "Heat Detector": "#E67E22",
    "Duct Detector": "#D35400",
    "Beam Detector": "#C0392B",
    "VESDA Detector": "#922B21",
    "Fire Detector": "#E74C3C",
    "Detector": "#E74C3C",
    "Pull Station": "#F39C12",
    "Break Glass": "#F1C40F",
    "Manual Call Point": "#F39C12",
    "Horn/Strobe": "#3498DB",
    "Horn": "#2980B9",
    "Strobe": "#1ABC9C",
    "Speaker": "#2ECC71",
    "Alarm Siren": "#E74C3C",
    "Alarm Device": "#3498DB",
    "Fire Alarm": "#3498DB",
    "Aspirating Smoke Detector": "#922B21",
    "Notification Appliance Circuit": "#3498DB",
    "Fire Alarm Control Panel": "#9B59B6",
    "Fire Panel": "#9B59B6",
    "Fire Brigade Panel": "#8E44AD",
    "Annunciator": "#8E44AD",
    "Monitor Module": "#27AE60",
    "Control Module": "#16A085",
    "Monitor/Control Module": "#1ABC9C",
    "Module": "#1ABC9C",
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
    "Emergency Light": "#F1C40F",
    "Emergency Exit Sign": "#2ECC71",
    "Exit Sign": "#27AE60",
    "Fire Extinguisher": "#E67E22",
    "Fire Cabinet": "#795548",
    "Fire Hydrant": "#2980B9",
    "Fire Hydrant (BIE)": "#2980B9",
    "Fire Standpipe": "#34495E",
    "Fire Pump": "#8E44AD",
    "Fire Pipe": "#546E7A",
    "Pressurized Pipe": "#455A64",
    "Overhead Pipe": "#607D8B",
    "Fire Hose": "#2980B9",
    "Gas Shutoff Valve": "#C0392B",
    "First Aid Kit": "#27AE60",
    "Evacuation Route": "#2ECC71",
}

DEFAULT_COLOR = "#95A5A6"

# Colors for legend system categories
CATEGORY_COLORS: dict[str, str] = {
    "Fire Alarm": "#E74C3C",
    "Access Control": "#3498DB",
    "Structured Cabling": "#E67E22",
    "BMS": "#9B59B6",
    "Video Surveillance": "#1ABC9C",
    "Public Address": "#2ECC71",
    "Other": "#95A5A6",
}

# Distinct color palette for individual symbol types (20 visually distinct colors)
SYMBOL_PALETTE = [
    "#E74C3C",  # red
    "#3498DB",  # blue
    "#2ECC71",  # green
    "#F39C12",  # orange
    "#9B59B6",  # purple
    "#1ABC9C",  # teal
    "#E67E22",  # dark orange
    "#2980B9",  # dark blue
    "#27AE60",  # dark green
    "#8E44AD",  # dark purple
    "#D35400",  # burnt orange
    "#16A085",  # dark teal
    "#C0392B",  # dark red
    "#2C3E50",  # navy
    "#F1C40F",  # yellow
    "#7D3C98",  # violet
    "#1F618D",  # steel blue
    "#117A65",  # forest green
    "#A04000",  # brown
    "#5B2C6F",  # deep purple
]


def get_category_color(category: str) -> str:
    """Get color for a legend system category."""
    return CATEGORY_COLORS.get(category, DEFAULT_COLOR)


def get_symbol_palette_color(index: int) -> str:
    """Get a distinct color from the palette by index."""
    return SYMBOL_PALETTE[index % len(SYMBOL_PALETTE)]

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

# Keywords in layer names that indicate fire alarm content
FIRE_LAYER_KEYWORDS = [
    "fire", "alarm", "fa_", "fa-", "f.a.",
    "incendio", "incêndio", "incendi",
    "smoke", "humo", "fumaca", "fumée",
    "detector", "detect",
    "sprinkler", "rociador", "sprinkleur",
    "suppression", "extinc",
    "notif", "horn", "strobe", "sirena", "alarma", "alarme",
    "emergency", "emergencia", "emergência",
    "evacu",
]


@dataclass
class MatchResult:
    """Result from dictionary matching with full audit metadata."""
    label: str
    method: str  # "exact_match", "substring_match", "intl_exact", "intl_substring"
    matched_term: str  # The dictionary key that triggered the match


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
    # Sub-grouping fields: when instances of the same block have different
    # attribute values (e.g., TYPE=AIM vs TYPE=AOM), we split them into
    # sub-groups. Each sub-group gets its own BlockInfo.
    sub_group_tag: str = ""    # Which ATTRIB tag was used to split (e.g., "TYPE")
    sub_group_value: str = ""  # The value for this sub-group (e.g., "AIM")


@dataclass
class ParseResult:
    """Internal result from parsing, includes symbols + analysis log + file path."""
    symbols: list[SymbolInfo] = field(default_factory=list)
    analysis: list[dict] = field(default_factory=list)
    dxf_path: str = ""
    # Blocks identified by fast-path dictionary
    fast_path_symbols: list[SymbolInfo] = field(default_factory=list)
    # Blocks that need AI classification
    ai_candidate_blocks: list[BlockInfo] = field(default_factory=list)
    # Drawing-wide context for AI
    all_block_names: list[str] = field(default_factory=list)
    all_layer_names: list[str] = field(default_factory=list)
    fire_layers: list[str] = field(default_factory=list)
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


def _fast_path_label(block_name: str) -> MatchResult | None:
    """Try to match a block name to a known fire alarm symbol using dictionaries.

    Returns a MatchResult with label + audit metadata, or None if uncertain.
    This is the fast path — only high-confidence matches.
    """
    name_upper = block_name.upper().strip()
    # Normalize all separators (underscores, hyphens, dots) to spaces for matching.
    # CAD block names use inconsistent separators: MONITOR_MODULE, MONITOR-MODULE, etc.
    name_normalized = re.sub(r'[_\-./\\]+', ' ', name_upper).strip()

    # 1. Exact match — English abbreviations
    if name_upper in KNOWN_SYMBOLS:
        return MatchResult(KNOWN_SYMBOLS[name_upper], "exact_match", name_upper)

    # 2. Exact match — International terms
    if name_normalized in KNOWN_SYMBOLS_INTL:
        return MatchResult(KNOWN_SYMBOLS_INTL[name_normalized], "intl_exact", name_normalized)

    # 3. Substring match — English (longer/more specific first)
    # Match against normalized name so "MONITOR_MODULE" matches "MONITOR MODULE"
    for abbrev, label in sorted(KNOWN_SYMBOLS.items(), key=lambda x: -len(x[0])):
        if len(abbrev) <= 3:
            # Short abbreviations need word boundary guards to avoid false positives
            pattern = r'(?<![A-Z0-9])' + re.escape(abbrev) + r'(?![A-Z0-9])'
            if re.search(pattern, name_normalized):
                return MatchResult(label, "substring_match", abbrev)
        else:
            if abbrev in name_normalized:
                return MatchResult(label, "substring_match", abbrev)

    # 4. Substring match — International terms
    for term, label in sorted(KNOWN_SYMBOLS_INTL.items(), key=lambda x: -len(x[0])):
        if term in name_normalized:
            return MatchResult(label, "intl_substring", term)

    return None


def _is_fire_layer(layer_name: str) -> bool:
    """Check if a layer name indicates fire alarm content."""
    name_lower = layer_name.lower()
    return any(kw in name_lower for kw in FIRE_LAYER_KEYWORDS)


def _get_symbol_color(label: str) -> str:
    """Get the visualization color for a symbol based on its label."""
    return SYMBOL_COLORS.get(label, DEFAULT_COLOR)


def _extract_legend_texts(doc) -> list[str]:
    """Extract text from the drawing that could be legend/schedule/symbol key info.

    Fire alarm drawings often have a symbol legend or device schedule that
    maps symbol names to descriptions. This text gives the AI critical context
    about what naming convention the drawing uses.
    """
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
    """Collect all metadata from a block definition for AI context."""
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


def _collect_model_texts(doc) -> list[dict]:
    """Scan all TEXT/MTEXT entities in model space and return their content + positions.

    These are the device code labels placed near symbols on the drawing —
    e.g., "S" next to a smoke detector, "AIM" next to an addressable module.
    They're standalone text entities, not ATTRIBs or block-internal text.
    """
    texts = []
    try:
        for layout in doc.layouts:
            if layout.name != "Model":
                continue
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
                else:
                    continue

                if not text or len(text) > 20:
                    continue  # Skip empty or very long text (not a device code)

                try:
                    pos = entity.dxf.insert
                    texts.append({
                        "text": text,
                        "x": pos.x,
                        "y": pos.y,
                    })
                except Exception:
                    pass
    except Exception:
        pass

    return texts


def _compute_search_radius(block_locations: dict[str, list[tuple[float, float]]]) -> float:
    """Compute an adaptive search radius for text-to-INSERT association.

    Uses 1.5% of the smaller drawing dimension. This captures text labels
    placed close to their symbol while avoiding false matches from neighboring
    symbols. Fire alarm text labels are typically placed within 1-3 feet of
    the symbol, which is a small fraction of the floor plan extent.
    """
    all_x = []
    all_y = []
    for locs in block_locations.values():
        for x, y in locs:
            all_x.append(x)
            all_y.append(y)

    if not all_x:
        return 500.0  # Safe default

    width = max(all_x) - min(all_x)
    height = max(all_y) - min(all_y)
    smaller_dim = min(width, height) if min(width, height) > 0 else max(width, height)

    if smaller_dim <= 0:
        return 500.0

    radius = smaller_dim * 0.015  # 1.5% of smaller dimension
    # Clamp to reasonable range
    return max(50.0, min(radius, 5000.0))


def _associate_text_with_inserts(
    block_instances: dict[str, list[dict]],
    model_texts: list[dict],
    radius: float,
) -> dict[str, int]:
    """Find the nearest short text entity for each INSERT instance.

    For each instance in block_instances, find TEXT entities within `radius`
    distance. If found, inject the text as a synthetic attribute '_NEARBY_LABEL'
    on the instance. This allows the existing sub-grouping and legend-matching
    code to use these text labels automatically.

    Returns:
        dict mapping text_value → count of instances matched (for logging).
    """
    if not model_texts:
        return {}

    # Pre-filter: only consider short text likely to be device codes (1-10 chars)
    code_texts = [t for t in model_texts if 1 <= len(t["text"]) <= 10]
    if not code_texts:
        return {}

    match_counts: dict[str, int] = defaultdict(int)
    total_matched = 0

    for block_name, instances in block_instances.items():
        for inst in instances:
            if "location" not in inst:
                continue

            ix, iy = inst["location"]
            best_text = None
            best_dist = float("inf")

            for ct in code_texts:
                dist = math.sqrt((ct["x"] - ix) ** 2 + (ct["y"] - iy) ** 2)
                if dist < best_dist and dist <= radius:
                    best_dist = dist
                    best_text = ct["text"]

            if best_text:
                # Inject as synthetic attribute — the existing sub-grouping
                # and legend-matching code will pick this up automatically
                inst["attribs"]["_NEARBY_LABEL"] = best_text
                match_counts[best_text] += 1
                total_matched += 1

    return dict(match_counts)


def _find_differentiating_tag(
    instances: list[dict],
    total_count: int,
) -> str | None:
    """Find the ATTRIB tag that best differentiates device types across instances.

    For a block like IT-DVC-FAM-Fire Modules-111 with 47 instances, some will have
    TYPE=AIM, others TYPE=AOM, etc. We need to find which tag varies meaningfully
    (not an ID field where every value is unique, not a constant field).

    Args:
        instances: List of dicts, each with "attribs" key containing {tag: value}.
        total_count: Total number of INSERT instances (some may lack attribs).

    Returns:
        The tag name that best differentiates device types, or None.
    """
    if not instances:
        return None

    # Collect all values per tag
    tag_values: dict[str, list[str]] = defaultdict(list)
    for inst in instances:
        for tag, value in inst.get("attribs", {}).items():
            tag_values[tag].append(value)

    if not tag_values:
        return None

    # Known device-type tag names (priority order). These are standard across
    # major CAD software: AutoCAD, Revit, BricsCAD, etc.
    PRIORITY_TAGS = [
        "TYPE", "DEVICE_TYPE", "DEVICE", "SYMBOL", "SYMBOL_TYPE",
        "MODEL", "PART_NUMBER", "DEVICE_NAME",
        "TAG", "NAME", "DESC", "DESCRIPTION",
    ]

    def _is_good_differentiator(tag: str, values: list[str]) -> bool:
        """A good differentiator has 2+ unique values but isn't an ID field."""
        unique = set(values)
        n_unique = len(unique)
        n_total = len(values)
        if n_unique < 2:
            return False  # Constant — same value everywhere
        if n_total >= 5 and n_unique > n_total * 0.8:
            return False  # ID-like — nearly every value is unique
        return True

    # Try priority tags first
    for ptag in PRIORITY_TAGS:
        if ptag in tag_values and _is_good_differentiator(ptag, tag_values[ptag]):
            return ptag

    # Fallback: find any tag that differentiates
    best_tag = None
    best_unique_count = 0
    for tag, values in tag_values.items():
        if _is_good_differentiator(tag, values):
            unique_count = len(set(values))
            if unique_count > best_unique_count:
                best_unique_count = unique_count
                best_tag = tag

    return best_tag


def _sub_group_block_instances(
    block_name: str,
    instances: list[dict],
    diff_tag: str,
    total_block_count: int,
    block_def_meta: dict,
    all_layers: set[str],
) -> list[BlockInfo]:
    """Split instances of a single block into sub-groups by a differentiating attribute.

    Args:
        block_name: Original DXF block name.
        instances: Per-instance data with attribs and locations.
        diff_tag: The attribute tag to sub-group by.
        total_block_count: Total INSERT count for this block (includes instances without attribs).
        block_def_meta: Block definition metadata (texts_inside, entity_types, etc.).
        all_layers: All layers this block appears on.

    Returns:
        List of BlockInfo objects, one per sub-group.
    """
    groups: dict[str, list[dict]] = defaultdict(list)
    no_attrib_instances = []

    for inst in instances:
        value = inst.get("attribs", {}).get(diff_tag, "")
        if value:
            groups[value].append(inst)
        else:
            no_attrib_instances.append(inst)

    # If there are instances without the differentiating attrib (e.g., some INSERTs
    # don't have attribs at all), create a catch-all sub-group
    instances_with_attribs = sum(len(g) for g in groups.values())
    unaccounted = total_block_count - instances_with_attribs - len(no_attrib_instances)

    result = []
    for value, group_instances in groups.items():
        locations = [inst["location"] for inst in group_instances if "location" in inst]
        layers = sorted(set(inst.get("layer", "") for inst in group_instances if inst.get("layer")))
        # Use representative attribs from first instance
        rep_attribs = group_instances[0].get("attribs", {}) if group_instances else {}

        result.append(BlockInfo(
            block_name=block_name,
            count=len(group_instances),
            layers=layers or sorted(all_layers),
            entity_types=block_def_meta.get("entity_types", {}),
            attribs=rep_attribs,
            texts_inside=block_def_meta.get("texts_inside", []),
            description=block_def_meta.get("description", ""),
            locations=locations,
            attdef_tags=block_def_meta.get("attdef_tags", {}),
            sub_group_tag=diff_tag,
            sub_group_value=value,
        ))

    # Catch-all for instances without the differentiating attribute
    remainder_count = len(no_attrib_instances) + unaccounted
    if remainder_count > 0:
        remainder_locations = [inst["location"] for inst in no_attrib_instances if "location" in inst]
        result.append(BlockInfo(
            block_name=block_name,
            count=remainder_count,
            layers=sorted(all_layers),
            entity_types=block_def_meta.get("entity_types", {}),
            attribs={},
            texts_inside=block_def_meta.get("texts_inside", []),
            description=block_def_meta.get("description", ""),
            locations=remainder_locations,
            attdef_tags=block_def_meta.get("attdef_tags", {}),
            sub_group_tag="",
            sub_group_value="",
        ))

    return result


def parse_dxf_file(filepath: str, use_fast_path: bool = True) -> ParseResult:
    """Parse a DXF file and extract all block references with metadata.

    When use_fast_path=True (default, no legend): uses dictionary matching as a
    fast path for obvious symbols. Remaining blocks go to AI.
    When use_fast_path=False (legend provided): skips dictionary matching entirely.
    ALL blocks are collected as AI candidates for legend-aware classification.
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
    fire_layers = []
    try:
        for layer in doc.layers:
            lname = layer.dxf.name
            layer_names.append(lname)
            if _is_fire_layer(lname):
                fire_layers.append(lname)
    except Exception:
        pass

    result.all_layer_names = layer_names
    result.fire_layers = fire_layers

    if layer_names:
        result.log("info", f"Layers in drawing: {len(layer_names)} total")
        if len(layer_names) <= 20:
            result.log("info", f"Layer names: {', '.join(layer_names)}")
        else:
            result.log("info", f"Layer names (first 20): {', '.join(layer_names[:20])}...")

    if fire_layers:
        result.log("success", f"Fire-related layers detected: {', '.join(fire_layers)}")
    else:
        result.log("info", "No fire-specific layer names found (will analyze all layers)")

    # Step 4: Extract legend/schedule text for AI context
    legend_texts = _extract_legend_texts(doc)
    result.legend_texts = legend_texts
    if legend_texts:
        result.log("success", f"Found {len(legend_texts)} legend/schedule text elements for AI context")

    # Step 5: Enumerate layouts and scan all INSERT entities
    layout_names = [layout.name for layout in doc.layouts]
    result.log("info", f"Layouts found: {len(layout_names)} — {', '.join(layout_names)}")

    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    block_layers: dict[str, set[str]] = defaultdict(set)
    block_attribs: dict[str, dict[str, str]] = {}
    skipped_blocks: dict[str, int] = defaultdict(int)
    attrib_errors: dict[str, str] = {}  # Track ATTRIB extraction failures
    # Per-instance data for sub-grouping: {block_name: [{attribs: {}, location: (x,y), layer: ""}]}
    block_instances: dict[str, list[dict]] = defaultdict(list)

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

            if etype in ("INSERT", "MINSERT"):
                block_name = entity.dxf.name
                total_inserts += 1
                layout_insert_count += 1

                if _should_skip_block(block_name):
                    skipped_blocks[block_name] += 1
                    continue

                # Only count and collect data from model space.
                # Paper space contains legends, title blocks, and viewports —
                # not real device placements. Counting paper space inserts
                # would inflate device counts (e.g., legend sample symbols).
                if not is_model_space:
                    continue

                # MINSERT = arrayed block insertions. Count = rows × cols.
                if etype == "MINSERT":
                    row_count = getattr(entity.dxf, 'row_count', 1) or 1
                    col_count = getattr(entity.dxf, 'column_count', 1) or 1
                    insert_multiplier = row_count * col_count
                else:
                    insert_multiplier = 1

                block_counts[block_name] += insert_multiplier

                # Collect per-instance data for sub-grouping
                instance_data: dict = {"attribs": {}}

                try:
                    block_layers[block_name].add(entity.dxf.layer)
                    instance_data["layer"] = entity.dxf.layer
                except Exception:
                    pass

                try:
                    if hasattr(entity, "attribs") and entity.attribs:
                        instance_attribs = {}
                        for attrib in entity.attribs:
                            tag = attrib.dxf.tag.upper().strip()
                            value = attrib.dxf.text.strip()
                            if value:
                                instance_attribs[tag] = value
                        instance_data["attribs"] = instance_attribs
                        # Also keep first-instance attribs for backward compat
                        if instance_attribs and block_name not in block_attribs:
                            block_attribs[block_name] = dict(instance_attribs)
                except Exception as e:
                    attrib_errors[block_name] = str(e)

                try:
                    insert_point = entity.dxf.insert
                    loc = (round(insert_point.x, 2), round(insert_point.y, 2))
                    block_locations[block_name].append(loc)
                    instance_data["location"] = loc
                except Exception:
                    pass

                # For MINSERT, add multiple instances for the array
                for _ in range(insert_multiplier):
                    block_instances[block_name].append(instance_data)

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

    # Step 5a: Nearby text label scanning
    # Fire alarm drawings have device code labels ("S", "H", "AIM", "AOM") placed
    # as TEXT/MTEXT entities near each symbol. These are the codes shown in the legend.
    # We scan all text in model space, find the nearest short text to each INSERT,
    # and inject it as a synthetic attribute '_NEARBY_LABEL' on the instance data.
    # This feeds directly into sub-grouping and legend code matching.
    model_texts = _collect_model_texts(doc)
    if model_texts:
        search_radius = _compute_search_radius(block_locations)
        result.log("info",
            f"Text label scan: {len(model_texts)} TEXT/MTEXT entities in model space, "
            f"search radius: {search_radius:.0f} units"
        )

        text_match_counts = _associate_text_with_inserts(
            block_instances, model_texts, search_radius
        )

        if text_match_counts:
            total_labeled = sum(text_match_counts.values())
            total_inserts_in_model = sum(block_counts.values())
            # Show top labels found
            top_labels = sorted(text_match_counts.items(), key=lambda x: -x[1])[:20]
            label_summary = ", ".join(f'"{t}"×{c}' for t, c in top_labels)
            result.log("success",
                f"Nearby text labels found: {total_labeled}/{total_inserts_in_model} "
                f"INSERT instances matched to text labels"
            )
            result.log("section",
                f"TEXT LABEL SCAN — {len(text_match_counts)} unique labels across {total_labeled} instances"
            )
            for text, count in top_labels:
                result.log("detail", f'  "{text}" — found near {count} INSERT instances')
            logger.info(
                f"=== TEXT LABEL SCAN: {total_labeled}/{total_inserts_in_model} instances labeled. "
                f"Top: {label_summary} ==="
            )
        else:
            result.log("info",
                "Text label scan: no short text found near INSERT positions "
                f"(radius={search_radius:.0f} units)"
            )
    else:
        result.log("info", "Text label scan: no TEXT/MTEXT entities found in model space")

    # Step 5b: ATTRIB inspection — debug what attribute data we actually collected
    blocks_with_attribs = {bn: instances for bn, instances in block_instances.items()
                           if any(inst.get("attribs") for inst in instances)}
    blocks_without_attribs = {bn for bn in block_counts if bn not in blocks_with_attribs}
    logger.info(
        f"=== ATTRIB INSPECTION: {len(blocks_with_attribs)}/{len(block_counts)} blocks have ATTRIBs, "
        f"{len(blocks_without_attribs)} have NONE ==="
    )
    for bn, instances in sorted(blocks_with_attribs.items()):
        sample = next((inst["attribs"] for inst in instances if inst.get("attribs")), {})
        logger.info(f"  ATTRIBS: \"{bn}\" — sample: {sample}")

    result.log("section",
        f"ATTRIB INSPECTION — {len(blocks_with_attribs)}/{len(block_counts)} blocks have per-instance ATTRIBs"
    )

    if blocks_with_attribs:
        for bn in sorted(blocks_with_attribs.keys()):
            instances = blocks_with_attribs[bn]
            instances_with = sum(1 for inst in instances if inst.get("attribs"))
            instances_without = len(instances) - instances_with
            # Collect all unique tags and sample values
            all_tags: dict[str, set[str]] = defaultdict(set)
            for inst in instances:
                for tag, val in inst.get("attribs", {}).items():
                    all_tags[tag].add(val)
            tag_summary = ", ".join(
                f'{tag}=[{", ".join(sorted(list(vals))[:5])}{"..." if len(vals) > 5 else ""}] ({len(vals)} unique)'
                for tag, vals in sorted(all_tags.items())
            )
            result.log("detail",
                f'  "{bn}" — {instances_with}/{len(instances)} have attribs, '
                f'{instances_without} empty. Tags: {tag_summary}'
            )
    else:
        result.log("detail", "  No blocks have per-instance ATTRIB data at all")
        result.log("detail", "  This means INSERT entities lack ATTRIB sub-entities (common in DWG→DXF conversion)")

    if blocks_without_attribs:
        # Show up to 10 blocks without attribs
        no_attr_list = sorted(blocks_without_attribs)[:10]
        result.log("detail",
            f"  Blocks with NO attribs ({len(blocks_without_attribs)}): "
            + ", ".join(f'"{bn}" (×{block_counts[bn]})' for bn in no_attr_list)
            + ("..." if len(blocks_without_attribs) > 10 else "")
        )

    if attrib_errors:
        result.log("warning",
            f"ATTRIB extraction errors ({len(attrib_errors)}): "
            + ", ".join(f'"{bn}": {err}' for bn, err in list(attrib_errors.items())[:5])
        )

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

    # Step 6b: Block definition content debug — show texts_inside and attdef_tags
    blocks_with_content = {bn: meta for bn, meta in block_def_metadata.items()
                           if meta.get("texts_inside") or meta.get("attdef_tags")}
    if blocks_with_content:
        result.log("section",
            f"BLOCK DEFINITION CONTENT — {len(blocks_with_content)}/{len(block_def_metadata)} blocks have text/attdefs"
        )
        for bn in sorted(blocks_with_content.keys()):
            meta = blocks_with_content[bn]
            parts = []
            if meta.get("texts_inside"):
                parts.append(f'texts={meta["texts_inside"][:5]}')
            if meta.get("attdef_tags"):
                parts.append(f'attdefs={dict(list(meta["attdef_tags"].items())[:5])}')
            if meta.get("description"):
                parts.append(f'desc="{meta["description"][:80]}"')
            result.log("detail",
                f'  "{bn}" (×{block_counts.get(bn, "?")}) — {", ".join(parts)}'
            )
    else:
        result.log("section",
            f"BLOCK DEFINITION CONTENT — 0/{len(block_def_metadata)} blocks have text or attdef content"
        )

    # Step 7: Propagate counts through nesting hierarchy (BFS)
    # IMPORTANT: Only propagate to blocks that were directly inserted on the
    # drawing. Without this guard, the BFS creates hundreds of phantom entries
    # for sub-components (scale rects, structural columns, text frames) that
    # were never placed as independent symbols — they're just internal parts
    # of other block definitions.
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

    # Step 9: Classify blocks — fast path vs AI candidates
    # When use_fast_path=False (legend uploaded), ALL blocks go to AI as candidates.
    # The legend provides the authoritative symbol dictionary, so we skip hardcoded patterns.
    #
    # NEW: Sub-grouping. When different INSERTs of the same block have different
    # attribute values (e.g., IT-DVC-FAM-Fire Modules-111 with TYPE=AIM vs TYPE=AOM),
    # split them into separate BlockInfo entries so each device type can be classified
    # independently. This is critical for drawings where one generic block is used for
    # multiple device types differentiated by ATTRIB values.
    result.all_block_names = sorted(block_counts.keys())
    fast_path_count = 0
    ai_candidate_count = 0
    sub_grouped_count = 0

    for block_name, count in sorted(block_counts.items(), key=lambda x: -x[1]):
        if use_fast_path:
            match = _fast_path_label(block_name)
        else:
            match = None  # Skip dictionary — legend is source of truth

        if match is not None:
            # Fast path: dictionary matched with high confidence
            fast_path_count += 1
            layers = sorted(block_layers.get(block_name, set()))
            symbol = SymbolInfo(
                block_name=block_name,
                label=match.label,
                count=count,
                locations=block_locations.get(block_name, []),
                color=_get_symbol_color(match.label),
                confidence="high",
                source="dictionary",
            )
            result.fast_path_symbols.append(symbol)
            result.symbols.append(symbol)
            result.audit.append(AuditEntry(
                block_name=block_name,
                label=match.label,
                count=count,
                method=match.method,
                confidence="high",
                matched_term=match.matched_term,
                layers=layers,
            ))
        else:
            layers = sorted(block_layers.get(block_name, set()))
            meta = block_def_metadata.get(block_name, {})
            instances = block_instances.get(block_name, [])

            # Try sub-grouping: check if instances have a differentiating attribute
            diff_tag = _find_differentiating_tag(instances, count)
            n_with_attribs = sum(1 for inst in instances if inst.get("attribs"))
            logger.debug(
                f"Sub-group check: \"{block_name}\" — {len(instances)} instances, "
                f"{n_with_attribs} with attribs, diff_tag={diff_tag!r}"
            )

            if diff_tag:
                # Sub-group this block by the differentiating attribute
                sub_groups = _sub_group_block_instances(
                    block_name=block_name,
                    instances=instances,
                    diff_tag=diff_tag,
                    total_block_count=count,
                    block_def_meta=meta,
                    all_layers=block_layers.get(block_name, set()),
                )
                for sg in sub_groups:
                    ai_candidate_count += 1
                    result.ai_candidate_blocks.append(sg)
                sub_grouped_count += 1
                result.log(
                    "info",
                    f'Sub-grouped "{block_name}" by {diff_tag}: '
                    f'{", ".join(f"{sg.sub_group_value}={sg.count}" for sg in sub_groups if sg.sub_group_value)}'
                    f'{" + " + str(sum(sg.count for sg in sub_groups if not sg.sub_group_value)) + " untagged" if any(not sg.sub_group_value for sg in sub_groups) else ""}'
                )
            else:
                # No sub-grouping — single BlockInfo as before
                ai_candidate_count += 1
                result.ai_candidate_blocks.append(BlockInfo(
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

    if use_fast_path:
        result.log(
            "info",
            f"Fast-path identified: {fast_path_count} symbol types "
            f"({sum(s.count for s in result.fast_path_symbols)} devices)"
        )
    else:
        result.log(
            "info",
            "Legend mode: skipping hardcoded patterns — all blocks sent to AI with legend context"
        )
    if sub_grouped_count > 0:
        result.log(
            "info",
            f"Sub-grouped {sub_grouped_count} blocks by per-instance attributes"
        )
    if ai_candidate_count > 0:
        result.log(
            "info",
            f"{ai_candidate_count} blocks queued for AI classification"
        )

    total = sum(s.count for s in result.symbols)
    result.log("success", f"Detection complete: {len(result.symbols)} symbol types, {total} total devices (pre-AI)")

    return result


def _merge_dxf_result(result: ParseResult, dxf_result: ParseResult, dxf_path: str):
    """Copy all parse data from a DXF parse into the DWG result."""
    result.analysis.extend(dxf_result.analysis)
    result.symbols = dxf_result.symbols
    result.fast_path_symbols = dxf_result.fast_path_symbols
    result.ai_candidate_blocks = dxf_result.ai_candidate_blocks
    result.all_block_names = dxf_result.all_block_names
    result.all_layer_names = dxf_result.all_layer_names
    result.fire_layers = dxf_result.fire_layers
    result.legend_texts = dxf_result.legend_texts
    result.audit = dxf_result.audit
    result.xref_warnings = dxf_result.xref_warnings
    result.dxf_path = dxf_path


def parse_dwg_file(filepath: str, use_fast_path: bool = True) -> ParseResult:
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
            _merge_dxf_result(result, parse_dxf_file(dxf_path, use_fast_path=use_fast_path), dxf_path)
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
            _merge_dxf_result(result, parse_dxf_file(dxf_path, use_fast_path=use_fast_path), dxf_path)
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
        _merge_dxf_result(result, parse_dxf_file(dxf_path, use_fast_path=use_fast_path), dxf_path)
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
