from pydantic import BaseModel


class SymbolInfo(BaseModel):
    block_name: str
    label: str  # User-friendly name — legend name when matched, else dictionary/AI label
    count: int
    locations: list[tuple[float, float]]  # ALL (x, y) insertion points
    color: str = "#95A5A6"  # Category color for visualization
    confidence: str = "high"  # "high" | "medium" | "low" | "manual"
    source: str = "dictionary"  # "dictionary" | "ai" | "legend" | "manual"
    block_variants: list[str] = []  # Individual block names before consolidation
    original_count: int | None = None  # Pre-override count (null if never overridden)
    # Legend matching (Phase 1) — populated after match-legend API call
    matched_legend: "LegendDevice | None" = None  # Full legend entry with description
    match_confidence: str | None = None  # "high" | "medium" | "low" | None
    original_label: str | None = None  # Pre-legend label (dictionary/AI guess) for audit
    svg_icon: str | None = None  # Generated SVG icon markup (Phase 2)


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


# ── Legend Models ──────────────────────────────────────────────────


class LegendDevice(BaseModel):
    name: str  # Full device name (e.g., "Main Fire Alarm Control Panel")
    abbreviation: str | None = None  # Short code (e.g., "MFACP")
    category: str  # System/section (e.g., "Fire Alarm System")
    symbol_description: str  # Detailed visual description for SVG generation
    svg_icon: str | None = None  # Generated SVG icon markup (Phase 2)


class LegendParseResponse(BaseModel):
    legend_id: str
    filename: str
    devices: list[LegendDevice]
    categories_found: list[str]
    total_device_types: int
    analysis: list[AnalysisStep] = []
    notes: str = ""


# Resolve forward reference: SymbolInfo.matched_legend → LegendDevice
SymbolInfo.model_rebuild()
