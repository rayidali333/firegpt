from pydantic import BaseModel


class SymbolInfo(BaseModel):
    block_name: str
    label: str  # User-friendly name (e.g., "Smoke Detector")
    count: int
    locations: list[tuple[float, float]]  # ALL (x, y) insertion points
    color: str = "#95A5A6"  # Category color for visualization


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
