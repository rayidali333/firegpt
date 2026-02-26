from pydantic import BaseModel


class SymbolInfo(BaseModel):
    block_name: str
    label: str  # User-friendly name (e.g., "Smoke Detector")
    count: int
    sample_locations: list[tuple[float, float]]  # First few (x, y) insertion points


class ParseResponse(BaseModel):
    drawing_id: str
    filename: str
    file_type: str
    symbols: list[SymbolInfo]
    total_symbols: int


class ChatRequest(BaseModel):
    drawing_id: str
    message: str


class ChatResponse(BaseModel):
    response: str
