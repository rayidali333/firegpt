"""
DXF/DWG Parser — Core symbol detection engine.

DXF files store reusable symbols as "blocks" (block definitions).
When a symbol is placed on a drawing, it creates an INSERT entity
that references the block by name, with a position (x, y, z).

For fire alarm drawings, symbols like SD (Smoke Detector), HD (Heat Detector),
PS (Pull Station) are stored as named blocks. We count INSERT references
to each block to get accurate symbol counts.

IMPORTANT: Block names are NOT standardized. Different firms, languages,
and CAD standards use different naming conventions. This parser supports
English, Spanish, Portuguese, and French fire alarm vocabulary.
"""

import re
import subprocess
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import ezdxf
from fastapi import HTTPException

from app.models import SymbolInfo

# ────────────────────────────────────────────────────────
# Symbol recognition dictionaries
# ────────────────────────────────────────────────────────

# English fire alarm abbreviations (most common in US/UK/Canada drawings)
# NOTE: In fire alarm context, SPK = Speaker (voice evacuation), NOT Sprinkler.
# Sprinklers live on separate plumbing/sprinkler drawings and use SPRK/SPRINKLER.
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

# International fire alarm vocabulary (Spanish, Portuguese, French, Italian)
# These use substring matching, so order matters — longer/more specific first
KNOWN_SYMBOLS_INTL = {
    # Spanish (Argentina, Spain, Mexico, etc.)
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
    # Portuguese (Brazil, Portugal)
    "DETECTOR DE FUMACA": "Smoke Detector",
    "DETECTOR DE FUMACO": "Smoke Detector",
    "ACIONADOR MANUAL": "Pull Station",
    "BOTOEIRA": "Pull Station",
    "AVISADOR SONORO": "Horn",
    "SINALIZADOR VISUAL": "Strobe",
    "SAIDA DE EMERGENCIA": "Emergency Exit Sign",
    "EXTINTOR DE INCENDIO": "Fire Extinguisher",
    "SPRINKLER": "Sprinkler",
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

# Block names to always skip (only truly internal AutoCAD objects)
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

# ────────────────────────────────────────────────────────
# Non-fire-alarm block filters
# ────────────────────────────────────────────────────────
# Keywords that indicate a block is NOT a fire alarm device.
# Applied only to blocks that failed all positive identification methods.
# Matched against the normalized (uppercased, separators→spaces) block name.
NON_FIRE_KEYWORDS = [
    # Furniture
    "CHAIR", "SOFA", "TABLE", "DESK", "BED ", "BEDS", "CABINET", "SHELF",
    "BENCH", "STOOL", "WARDROBE", "BOOKCASE", "CREDENZA", "COUCH",
    "OTTOMAN", "ARMCHAIR", "MATTRESS", "DRESSER", "NIGHTSTAND", "CUSHION",
    "LOUNGE", "BARSTOOL", "RECLINER", "FUTON", "SIDEBOARD", "HUTCH",
    "FILING", "CUBICLE", "WORKSTATION",
    # Plumbing / sanitary
    "TOILET", "SINK", "DRAIN", "BATHTUB", "SHOWER", "FAUCET", "URINAL",
    "BIDET", "LAVATORY", "BASIN", "WC FIXTURE", "SANITARY", "TOILET PAPER",
    "SOAP DISPENSER", "TOWEL", "DURAVIT", "FLUSHING", "WATER CLOSET",
    "PLUMBING", "SEWER", "WASTE", "CISTERN", "VANITY",
    # Kitchen / appliances
    "REFRIGERATOR", "OVEN", "MICROWAVE", "DISHWASHER", "COOKTOP",
    "RANGE HOOD", "KITCHEN SINK", "COFFEE", "VENDING",
    # Architectural elements
    "DOOR", "WINDOW", "RAILING", "STAIR", "CURTAIN WALL", "MULLION",
    "PARAPET", "CEILING GRID", "FLOOR PATTERN", "TILE", "MOLDING",
    "BASEBOARD", "THRESHOLD", "GLAZING", "LOUVER", "SHUTTER",
    "BALUSTRADE", "HANDRAIL", "NEWEL", "TREAD", "RISER", "LANDING",
    "ELEVATOR", "ESCALATOR", "REVOLVING DOOR",
    # Structural
    "FOOTING", "FOUNDATION", "REBAR", "CONCRETE", "STEEL BEAM",
    "STEEL COLUMN", "TRUSS", "PILE", "SLAB",
    # Annotation / CAD drafting
    "GRID", "GRIDLINE", "TITLE", "BORDER", "NORTH", "ARROW",
    "DIMENSION", "LEADER", "TAG", "KEYNOTE", "SECTION", "DETAIL",
    "CALLOUT", "REVISION", "MATCHLINE", "BREAK LINE", "CENTERLINE",
    "VIEWPORT", "SCALE BAR", "LEGEND",
    "SHEET FRAME", "TITLE BLOCK", "TITLEBLOCK", "PLOT FRAME",
    "DRAWING BORDER", "SHEET BORDER", "SHEET FORMAT",
    # Landscape / site
    "TREE", "PLANT", "SHRUB", "BUSH", "GRASS", "FLOWER", "LANDSCAPE",
    "PAVING", "CURB", "BOLLARD", "FENCE", "GATE",
    # Vehicles / transport
    "CAR ", "VEHICLE", "PARKING", "BICYCLE", "MOTORCYCLE", "TRUCK",
    # People / accessibility
    "PERSON", "PEOPLE", "FIGURE", "WHEELCHAIR", "ACCESSIBLE",
    # HVAC (non-fire)
    "DIFFUSER", "VENT", "AIR HANDLING", "AHU", "CHILLER", "BOILER",
    "RADIATOR", "FCU", "FAN COIL", "THERMOSTAT", "CONDENSING",
    "COOLING TOWER", "SUPPLY AIR", "RETURN AIR", "EXHAUST FAN",
    # Electrical (non-fire)
    "OUTLET", "RECEPTACLE", "LIGHT FIXTURE", "LUMINAIRE", "LAMP",
    "TRANSFORMER", "PANELBOARD", "SWITCHGEAR", "MOTOR", "GENERATOR",
    "UPS", "CONDUIT RUN", "CABLE TRAY", "JUNCTION",
    # IT / data
    "DATA OUTLET", "TELEPHONE", "CCTV", "CAMERA",
    "ACCESS POINT", "NETWORK",
    # Medical
    "MEDICAL GAS", "NURSE CALL", "BED HEAD",
    # Misc non-fire
    "SIGN ", "SIGNAGE", "ARTWORK", "MIRROR", "CLOCK",
    "COAT HOOK", "UMBRELLA", "TRASH", "WASTE BIN", "RECYCLING",
]

# Prefixes in block names that typically indicate non-fire-alarm disciplines
# Matched against the start of the normalized block name
NON_FIRE_PREFIXES = [
    "AR ",   # Architectural
    "AR-",
    "AR_",
    "FUR ",  # Furniture
    "FUR-",
    "FUR_",
    "PFX",   # Plumbing Fixtures
    "ST ",   # Structural
    "ST-",
    "ST_",
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
class UnrecognizedBlock:
    """Metadata about a block that couldn't be identified by dictionary matching."""
    block_name: str
    count: int
    layers: list[str] = field(default_factory=list)
    entity_types: dict[str, int] = field(default_factory=dict)
    attribs: dict[str, str] = field(default_factory=dict)
    texts_inside: list[str] = field(default_factory=list)
    description: str = ""
    locations: list[tuple[float, float]] = field(default_factory=list)


@dataclass
class ParseResult:
    """Internal result from parsing, includes symbols + analysis log + file path."""
    symbols: list[SymbolInfo] = field(default_factory=list)
    analysis: list[dict] = field(default_factory=list)
    dxf_path: str = ""
    unrecognized_blocks: list[UnrecognizedBlock] = field(default_factory=list)

    def log(self, type: str, message: str):
        self.analysis.append({"type": type, "message": message})


def _should_skip_block(block_name: str) -> bool:
    """Check if a block name is an AutoCAD system/internal block."""
    for pattern in SKIP_PATTERNS:
        if re.match(pattern, block_name, re.IGNORECASE):
            return True
    return False


def _is_obvious_non_fire(block_name: str, layers: set[str] | None = None) -> bool:
    """Check if a block is obviously NOT a fire alarm device.

    Only called for blocks that failed all positive identification methods
    (dictionary, attribs, block def content). Uses keyword and prefix matching
    to filter out furniture, plumbing, architectural, and annotation blocks
    before wasting AI tokens on them.
    """
    name_normalized = block_name.upper().replace("_", " ").replace("-", " ").strip()

    # Very long block names (>80 chars) are almost certainly annotation/title
    # block elements, not fire alarm device symbols
    if len(name_normalized) > 80:
        return True

    # Check prefixes (AR-, FUR-, PFX-, ST-, etc.)
    for prefix in NON_FIRE_PREFIXES:
        if name_normalized.startswith(prefix.upper()):
            return True

    # Check keywords — use word-boundary matching for short keywords (≤5 chars)
    # to avoid false positives like "DOOR" matching "INDOOR"
    for keyword in NON_FIRE_KEYWORDS:
        kw_upper = keyword.upper().strip()
        if len(kw_upper) <= 5:
            pattern = r'(?<![A-Z])' + re.escape(kw_upper) + r'(?![A-Z])'
            if re.search(pattern, name_normalized):
                return True
        else:
            if kw_upper in name_normalized:
                return True

    return False


def _guess_label(block_name: str) -> str:
    """Try to match a block name to a known fire alarm symbol.

    Checks English abbreviations first, then international terms.
    Uses both exact and substring matching.
    Normalizes underscores/hyphens to spaces for international matching.
    """
    name_upper = block_name.upper().strip()
    # Normalize separators for international matching (CAD blocks use _ instead of spaces)
    name_normalized = name_upper.replace("_", " ").replace("-", " ").strip()

    # 1. Exact match — English abbreviations (use raw name)
    if name_upper in KNOWN_SYMBOLS:
        return KNOWN_SYMBOLS[name_upper]

    # 2. Exact match — International terms (use normalized name)
    if name_normalized in KNOWN_SYMBOLS_INTL:
        return KNOWN_SYMBOLS_INTL[name_normalized]

    # 3. Substring match — English abbreviations
    # Sort by key length descending so longer/more specific matches win.
    # e.g., "SPEAKER" matches before "SPK", "ALARM SIREN" before "ALARM",
    # "CONTROL MODULE" before "MODULE", "SPRINKLER" before "SPK".
    for abbrev, label in sorted(KNOWN_SYMBOLS.items(), key=lambda x: -len(x[0])):
        if len(abbrev) <= 3:
            # Word-boundary match: check that abbrev is surrounded by
            # non-alphanumeric chars (or start/end of string)
            pattern = r'(?<![A-Z0-9])' + re.escape(abbrev) + r'(?![A-Z0-9])'
            if re.search(pattern, name_upper):
                return label
        else:
            if abbrev in name_upper:
                return label

    # 4. Substring match — International terms (against normalized name)
    # Sort by length descending so longer terms match first
    for term, label in sorted(KNOWN_SYMBOLS_INTL.items(), key=lambda x: -len(x[0])):
        if term in name_normalized:
            return label

    # 5. Clean up the block name for display
    return name_normalized


def _get_symbol_color(label: str) -> str:
    """Get the visualization color for a symbol based on its label."""
    return SYMBOL_COLORS.get(label, DEFAULT_COLOR)


# Attribute tags that typically describe what a block IS
_TYPE_ATTRIB_TAGS = {"TYPE", "TIPO", "NAME", "NOMBRE", "DESCRIPTION", "DESCRIPCION",
                     "DESC", "DEVICE", "DISPOSITIVO", "SYMBOL", "SIMBOLO", "EQUIPO",
                     "DEVICE_TYPE", "DEVICE TYPE", "EQUIPMENT"}


def _guess_label_from_attribs(attrs: dict[str, str]) -> str | None:
    """Try to identify a symbol from its block attribute values.

    Professional CAD drawings often attach attributes like TYPE="SMOKE DETECTOR"
    to block references. This catches symbols that have non-standard block names.
    """
    # Check type-describing attributes first
    for tag in _TYPE_ATTRIB_TAGS:
        if tag in attrs:
            value = attrs[tag]
            # Try matching the attribute value against our dictionaries
            label = _guess_label(value)
            # If it matched to something meaningful (not just cleaned-up text)
            if label != value.upper().replace("_", " ").replace("-", " ").strip():
                return label
            # Even if no dictionary match, the attribute value itself is descriptive
            if len(value) > 2:
                return value.title()

    # Check ALL attribute values for fire alarm keywords
    all_values = " ".join(attrs.values()).upper()
    for term, label in KNOWN_SYMBOLS_INTL.items():
        if term in all_values:
            return label
    for abbrev, label in KNOWN_SYMBOLS.items():
        if abbrev in all_values:
            return label

    return None


def _match_known_label(text: str) -> str | None:
    """Check if any known symbol label appears as a substring in text.

    This is a reverse lookup: instead of matching block names against dictionaries,
    we check if the text already contains a recognized label (e.g., "Pull Station"
    appears in the description "Pull Station - Manual Alarm Activation").
    """
    text_upper = text.upper()
    # Check labels from both dictionaries (values, not keys)
    seen = set()
    for label in list(KNOWN_SYMBOLS.values()) + list(KNOWN_SYMBOLS_INTL.values()):
        if label not in seen and label.upper() in text_upper:
            seen.add(label)
            return label
    return None


def _guess_label_from_block_def(block, doc) -> str | None:
    """Try to identify a symbol from its block definition content.

    Scans three data sources inside the block definition:
    1. Block description field (DXF group code 4)
    2. ATTDEF entities (attribute definitions with default values)
    3. TEXT/MTEXT entities drawn inside the block (e.g., "SD", "HD")

    This is critical for *U anonymous dynamic blocks where the block name
    is meaningless but the internal content identifies the device.
    """
    # Source 1: Block description field
    try:
        desc = block.block.dxf.get("description", "")
        if desc and len(desc.strip()) > 1:
            # First try dictionary key matching
            label = _guess_label(desc.strip())
            if label != desc.strip().upper().replace("_", " ").replace("-", " ").strip():
                return label
            # Then try reverse label matching (e.g., "Pull Station" in description)
            label = _match_known_label(desc)
            if label:
                return label
    except Exception:
        pass

    # Source 2: ATTDEF entities (attribute definitions in the block)
    # Constant ATTDEFs are especially valuable — fixed, unchangeable text
    try:
        for attdef in block.attdefs():
            tag = attdef.dxf.tag.upper().strip()
            # Check the default text value
            default_text = attdef.dxf.text.strip()
            if default_text and tag in _TYPE_ATTRIB_TAGS:
                label = _guess_label(default_text)
                if label != default_text.upper().replace("_", " ").replace("-", " ").strip():
                    return label
                if len(default_text) > 2:
                    return default_text.title()
            # Check the prompt text (e.g., "Enter device type:")
            try:
                prompt = attdef.dxf.prompt.strip()
                if prompt:
                    for term, label in KNOWN_SYMBOLS_INTL.items():
                        if term in prompt.upper():
                            return label
            except Exception:
                pass
    except Exception:
        pass

    # Source 3: TEXT/MTEXT entities inside the block definition
    # Fire alarm symbols typically contain short labels like "SD", "HD", "PS"
    texts_found = []
    try:
        for entity in block:
            etype = entity.dxftype()
            if etype == "TEXT":
                text = entity.dxf.text.strip()
                if text and 1 <= len(text) <= 20:
                    texts_found.append(text)
            elif etype == "MTEXT":
                try:
                    text = entity.plain_text().strip()
                except Exception:
                    text = entity.text.strip() if entity.text else ""
                if text and 1 <= len(text) <= 20:
                    texts_found.append(text)
    except Exception:
        pass

    # Match block-internal text against known symbols
    for text in texts_found:
        label = _guess_label(text)
        if label != text.upper().replace("_", " ").replace("-", " ").strip():
            return label

    return None


def _is_fire_layer(layer_name: str) -> bool:
    """Check if a layer name indicates fire alarm content."""
    name_lower = layer_name.lower()
    return any(kw in name_lower for kw in FIRE_LAYER_KEYWORDS)


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

    # Step 4: Enumerate layouts
    layout_names = [layout.name for layout in doc.layouts]
    result.log("info", f"Layouts found: {len(layout_names)} — {', '.join(layout_names)}")

    block_counts: dict[str, int] = defaultdict(int)
    block_locations: dict[str, list[tuple[float, float]]] = defaultdict(list)
    block_layers: dict[str, set[str]] = defaultdict(set)
    block_attribs: dict[str, dict[str, str]] = {}  # block_name → {tag: value}
    skipped_blocks: dict[str, int] = defaultdict(int)

    # Phase 1: Scan ALL layouts (model space + all paper space layouts)
    total_entities = 0
    total_inserts = 0
    total_attribs_found = 0

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

                # Track which layer this block is on
                try:
                    block_layers[block_name].add(entity.dxf.layer)
                except Exception:
                    pass

                # Read block attributes (ATTRIB entities attached to INSERT)
                # These often contain TYPE, NAME, DESCRIPTION, TAG, etc.
                try:
                    if hasattr(entity, "attribs") and entity.attribs:
                        for attrib in entity.attribs:
                            tag = attrib.dxf.tag.upper().strip()
                            value = attrib.dxf.text.strip()
                            if value and block_name not in block_attribs:
                                block_attribs[block_name] = {}
                            if value:
                                block_attribs[block_name][tag] = value
                                total_attribs_found += 1
                except Exception:
                    pass

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

    # Log block attributes (critical for non-standard block name identification)
    if block_attribs:
        result.log("success", f"Block attributes found on {len(block_attribs)} blocks ({total_attribs_found} total attribute values)")
        for bname, attrs in list(block_attribs.items())[:10]:
            attr_str = ", ".join(f'{k}="{v}"' for k, v in attrs.items())
            result.log("info", f'Block "{bname}" attributes: {attr_str}')
    else:
        result.log("info", "No block attributes found (blocks have no ATTRIB data)")

    # Log block-to-layer mapping
    if block_layers:
        bl_entries = []
        for bname, layers in list(block_layers.items())[:10]:
            layer_str = ", ".join(sorted(layers))
            bl_entries.append(f'"{bname}" on layer [{layer_str}]')
        result.log("info", f"Block layers: {'; '.join(bl_entries)}")

    # Phase 2: Build nested reference map from block definitions
    # Also scan block content for identification (text, ATTDEFs, description)
    nested_ref_counts: dict[str, dict[str, int]] = {}
    block_def_count = 0
    block_def_entities: dict[str, dict[str, int]] = {}
    block_def_labels: dict[str, str] = {}  # block_name → label from definition content

    for block in doc.blocks:
        if _should_skip_block(block.name):
            continue
        block_def_count += 1
        refs: dict[str, int] = defaultdict(int)
        entity_types: dict[str, int] = defaultdict(int)
        for entity in block:
            entity_types[entity.dxftype()] += 1
            if entity.dxftype() == "INSERT" and not _should_skip_block(entity.dxf.name):
                refs[entity.dxf.name] += 1
        if refs:
            nested_ref_counts[block.name] = dict(refs)
        if entity_types and block.name in block_counts:
            block_def_entities[block.name] = dict(entity_types)

        # For blocks that are actually used in the drawing, scan their definition
        # for identifying text, ATTDEFs, and description fields
        if block.name in block_counts:
            label_from_def = _guess_label_from_block_def(block, doc)
            if label_from_def:
                block_def_labels[block.name] = label_from_def

    result.log("info", f"Block definitions analyzed: {block_def_count}")

    if block_def_labels:
        result.log(
            "success",
            f"Block definition content identified {len(block_def_labels)} blocks: "
            + ", ".join(f'"{k}" → {v}' for k, v in list(block_def_labels.items())[:8])
        )

    # Log what's inside each detected block (helps debugging)
    if block_def_entities:
        for bname, etypes in list(block_def_entities.items())[:8]:
            etype_str = ", ".join(f"{t}: {c}" for t, c in sorted(etypes.items(), key=lambda x: -x[1])[:5])
            result.log("info", f'Block "{bname}" contains: {etype_str}')

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

    # Build result — WHITELIST approach: only include positively identified fire alarm devices.
    # Blocks that can't be identified are candidates for AI analysis, not included by default.
    symbols = []
    skipped_non_fire = 0
    ai_candidates = 0

    for block_name, count in sorted(block_counts.items(), key=lambda x: -x[1]):
        label = _guess_label(block_name)

        # Detection waterfall: block name → INSERT attribs → block definition content
        is_unrecognized = label == block_name.replace("_", " ").replace("-", " ").strip().upper()

        # Tier 2: If block name didn't match, try INSERT attributes
        if is_unrecognized:
            attrs = block_attribs.get(block_name, {})
            label_from_attribs = _guess_label_from_attribs(attrs) if attrs else None
            if label_from_attribs:
                label = label_from_attribs
                is_unrecognized = False
                result.log(
                    "success",
                    f'"{block_name}" identified as "{label}" from block attributes'
                )

        # Tier 3: If still unrecognized, try block definition content
        # (description field, ATTDEFs, internal TEXT/MTEXT)
        if is_unrecognized and block_name in block_def_labels:
            label = block_def_labels[block_name]
            is_unrecognized = False
            result.log(
                "success",
                f'"{block_name}" identified as "{label}" from block definition content'
            )

        # Check if this block is on a fire-related layer
        layers = block_layers.get(block_name, set())
        on_fire_layer = any(_is_fire_layer(l) for l in layers)

        if not is_unrecognized:
            # ✓ Positively identified as a fire alarm device — include it
            symbols.append(
                SymbolInfo(
                    block_name=block_name,
                    label=label,
                    count=count,
                    locations=block_locations.get(block_name, []),
                    color=_get_symbol_color(label),
                )
            )
            if on_fire_layer:
                result.log(
                    "success",
                    f'"{block_name}" ({label}) is on fire-related layer: '
                    f'{", ".join(l for l in layers if _is_fire_layer(l))}'
                )
        else:
            # Unrecognized block — check if it's obviously non-fire
            if _is_obvious_non_fire(block_name, layers):
                skipped_non_fire += 1
                continue

            # Not obviously non-fire — send to AI for identification
            ai_candidates += 1
            texts_inside = []
            desc = ""
            try:
                block_def = doc.blocks.get(block_name)
                if block_def:
                    try:
                        desc = block_def.block.dxf.get("description", "") or ""
                    except Exception:
                        pass
                    for entity in block_def:
                        etype = entity.dxftype()
                        if etype == "TEXT":
                            t = entity.dxf.text.strip()
                            if t:
                                texts_inside.append(t)
                        elif etype == "MTEXT":
                            try:
                                t = entity.plain_text().strip()
                            except Exception:
                                t = ""
                            if t:
                                texts_inside.append(t)
            except Exception:
                pass

            result.unrecognized_blocks.append(
                UnrecognizedBlock(
                    block_name=block_name,
                    count=count,
                    layers=sorted(layers),
                    entity_types=block_def_entities.get(block_name, {}),
                    attribs=block_attribs.get(block_name, {}),
                    texts_inside=texts_inside[:10],
                    description=desc,
                    locations=block_locations.get(block_name, []),
                )
            )

    if skipped_non_fire > 0:
        result.log(
            "info",
            f"Filtered out {skipped_non_fire} non-fire-alarm blocks "
            f"(furniture, plumbing, architectural, annotation, etc.)"
        )

    if ai_candidates > 0:
        result.log(
            "info",
            f"{ai_candidates} ambiguous blocks queued for AI identification"
        )

    result.symbols = symbols
    total = sum(s.count for s in symbols)
    result.log("success", f"Detection complete: {len(symbols)} symbol types, {total} total devices")

    if total == 0 and not result.unrecognized_blocks:
        result.log(
            "warning",
            "No symbols detected. The drawing may use non-standard block names, "
            "or content may be in an unsupported format (e.g., pure geometry without blocks)."
        )
    elif total == 0 and result.unrecognized_blocks:
        result.log(
            "info",
            "No symbols identified by dictionary matching. "
            "AI analysis will attempt to identify remaining blocks."
        )
    elif len(symbols) < 5 and total < 15:
        result.log(
            "warning",
            "Very few symbols detected. Possible causes: "
            "(1) DWG-to-DXF conversion lost data — try exporting DXF directly from AutoCAD; "
            "(2) Symbols are drawn as raw geometry instead of named blocks; "
            "(3) Dynamic blocks lost their names during conversion (showing as *U blocks)."
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
    result.log(
        "warning",
        "DWG conversion may lose data (dynamic block names, some entities). "
        "For best results, export DXF directly from AutoCAD or BricsCAD."
    )

    # Strategy 1: LibreDWG dwg2dxf
    dwg2dxf_path = _find_dwg2dxf()
    if dwg2dxf_path:
        result.log("info", f"Using LibreDWG converter: {dwg2dxf_path}")
        try:
            dxf_path = _convert_with_libredwg(filepath, dwg2dxf_path, result)
            dxf_result = parse_dxf_file(dxf_path)
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

    # Strategy 3: ezdxf recovery mode
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
