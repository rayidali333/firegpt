from pydantic import BaseModel


class SymbolInfo(BaseModel):
    block_name: str
    label: str  # User-friendly name (e.g., "Smoke Detector")
    count: int
    locations: list[tuple[float, float]]  # ALL (x, y) insertion points
    color: str = "#95A5A6"  # Category color for visualization
    confidence: str = "high"  # "high" (dictionary) | "medium" (AI) | "manual" (user override)
    source: str = "dictionary"  # "dictionary" | "ai" | "legend" | "manual"
    block_variants: list[str] = []  # Individual block names before consolidation
    original_count: int | None = None  # Pre-override count (null if never overridden)
    shape_code: str = "circle"  # Marker shape: "circle", "square", "diamond", "hexagon", "pentagon", "triangle"
    category: str = ""  # System category from legend (e.g., "Fire Alarm", "Access Control")
    legend_code: str = ""  # Symbol code from legend (e.g., "S", "MFACP", "SCM")
    legend_shape: str = ""  # Shape description from legend (e.g., "hexagon with S inside")
    svg_icon: str = ""  # AI-generated SVG icon matching the legend symbol


class AuditEntry(BaseModel):
    block_name: str
    label: str
    count: int
    method: str  # "exact_match" | "substring_match" | "intl_match" | "ai"
    confidence: str
    matched_term: str | None = None  # The dictionary key that triggered the match
    layers: list[str] = []


class AnalysisStep(BaseModel):
    type: str  # "info", "success", "warning", "error"
    message: str


class ParseResponse(BaseModel):
    drawing_id: str
    filename: str
    file_type: str
    symbols: list[SymbolInfo]
    total_symbols: int
    analysis: list[AnalysisStep] = []
    audit: list[AuditEntry] = []
    xref_warnings: list[str] = []
    legend_texts: list[str] = []


class ChatHistoryMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    drawing_id: str
    message: str
    history: list[ChatHistoryMessage] = []


class ChatResponse(BaseModel):
    response: str


class PreviewResponse(BaseModel):
    svg: str
    viewBox: str
    width: float
    height: float
    symbol_positions: dict[str, list[list[float]]] = {}  # block_name → [[x, y], ...] in SVG space
    position_debug: list[str] = []  # Diagnostic info for symbol position tracking


class SymbolOverride(BaseModel):
    label: str
    count: int


class ProjectDrawingInfo(BaseModel):
    """Metadata about a drawing within a project."""
    drawing_id: str
    filename: str
    file_type: str
    total_symbols: int
    symbol_types: int  # Number of distinct symbol types


class ProjectSummary(BaseModel):
    """Aggregated symbol counts across all drawings in a project."""
    project_id: str
    project_name: str
    total_drawings: int
    total_symbols: int
    total_types: int
    symbols: list[SymbolInfo]  # Merged symbols across all sheets
    per_sheet: dict[str, list[SymbolInfo]] = {}  # drawing_id → symbols for that sheet
    drawings: list[ProjectDrawingInfo] = []


class ProjectData(BaseModel):
    """A project = 1 confirmed legend + N drawings."""
    project_id: str
    name: str
    legend_id: str | None = None
    drawing_ids: list[str] = []  # Ordered list of drawing IDs in this project
    created_at: str = ""  # ISO timestamp


class ProjectChatRequest(BaseModel):
    project_id: str
    message: str
    history: list[ChatHistoryMessage] = []
    active_drawing_id: str | None = None  # Optional: focus on a specific sheet


class LegendSymbol(BaseModel):
    """A single symbol entry parsed from an uploaded legend sheet."""
    code: str  # Text code shown in symbol (e.g., "MFACP", "CR", "DS")
    name: str  # Full device name (e.g., "Main Fire Alarm Control Panel")
    category: str  # System category (e.g., "Fire Alarm", "Access Control", "BMS")
    shape: str = ""  # Visual shape description (e.g., "pentagon with S inside")
    shape_code: str = ""  # SVG marker shape: "circle", "square", "diamond", "pentagon", "hexagon", "triangle", "star"
    filled: bool = False  # Whether the symbol shape is filled/solid
    svg_icon: str = ""  # AI-generated SVG icon for this symbol


class LegendData(BaseModel):
    """Parsed legend data from a legend sheet upload."""
    legend_id: str
    filename: str
    symbols: list[LegendSymbol]
    total_symbols: int
    systems: list[str] = []  # Unique system categories found
