"""
Chat module — LLM-powered Q&A about uploaded drawings.

The parsed symbol data is tiny (~2-5KB JSON), so we inject it directly
into the system prompt. No RAG or vector DB needed.

System-agnostic: the system prompt adapts to whatever discipline the
legend describes (fire alarm, structured cabling, HVAC, electrical, etc.).
"""

import json
import logging
import os

from anthropic import AsyncAnthropic

from app.models import ParseResponse

logger = logging.getLogger(__name__)

client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global client
    if client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY not set. Add it to backend/.env"
            )
        client = AsyncAnthropic(api_key=api_key)
    return client


def _detect_system_type(drawing: ParseResponse) -> tuple[str, list[str]]:
    """Detect the building system type from legend categories on the symbols.

    Returns (system_type_description, list_of_categories).
    """
    categories: set[str] = set()
    for s in drawing.symbols:
        if s.matched_legend and s.matched_legend.category:
            categories.add(s.matched_legend.category)

    if not categories:
        return "building systems", []

    cat_list = sorted(categories)
    if len(cat_list) == 1:
        return cat_list[0].lower(), cat_list
    return ", ".join(cat_list).lower(), cat_list


def _build_system_prompt(drawing: ParseResponse) -> str:
    """Build a system prompt with the parsed drawing data injected.

    Adapts to the discipline detected from legend categories — works for
    fire alarm, structured cabling, HVAC, electrical, security, etc.
    """
    symbol_data = []
    for s in drawing.symbols:
        entry = {
            "block_name": s.block_name,
            "label": s.label,
            "count": s.count,
        }
        if s.matched_legend:
            entry["category"] = s.matched_legend.category
        if s.locations:
            entry["sample_locations"] = s.locations[:5]
        symbol_data.append(entry)

    data_json = json.dumps(symbol_data, indent=2)

    system_type, categories = _detect_system_type(drawing)

    category_context = ""
    if categories:
        category_context = f"\nSYSTEM CATEGORIES DETECTED: {', '.join(categories)}\n"

    return f"""You are FireGPT, a professional AI assistant for contractors and engineers \
working with construction drawings. You specialize in analyzing MEP (mechanical, electrical, \
plumbing) and building system drawings — including fire alarm, structured cabling, HVAC, \
electrical, security, and other building systems.

You are helping a contractor analyze a drawing file. The drawing contains {system_type} devices. \
Below is the extracted symbol data from "{drawing.filename}" ({drawing.file_type.upper()} format).
{category_context}
EXTRACTED SYMBOL DATA:
{data_json}

TOTAL SYMBOLS DETECTED: {drawing.total_symbols}

INSTRUCTIONS:
- Answer questions about symbol counts, types, and locations accurately.
- When asked about counts, use the exact numbers from the data above.
- If asked about a symbol type not in the data, say it was not found in this drawing.
- "block_name" is the technical name from the CAD file. "label" is the human-readable name.
- Help with bid estimation, device scheduling, and material takeoffs.
- Be concise and direct. Contractors need quick, accurate answers.
- If the user asks about something outside the drawing data, let them know you can only \
answer questions about the uploaded drawing.
- Format counts and lists clearly using markdown tables when appropriate.
- Use **bold** for important numbers and device names.

COST ESTIMATION GUIDELINES:
When asked about cost estimates, material pricing, or bid preparation:
1. Use your knowledge of current US market rates for the specific system type ({system_type}).
2. Present material costs and labor costs separately in a clear table.
3. Always provide LOW and HIGH estimate ranges.
4. Add 10-15% for project management, engineering, and overhead.
5. Add 10-15% contingency for unforeseen conditions.
6. Note that permits, engineering stamps, and inspection fees are additional.
7. Mention that actual costs vary by region, project complexity, and market conditions.
8. For wiring/cabling estimates, use average 75 feet per device unless the user specifies otherwise.
9. Round totals to the nearest $100 for cleanliness."""


async def chat_with_drawing(
    message: str,
    drawing: ParseResponse,
    history: list[dict] | None = None,
) -> str:
    """Send a message to the LLM with drawing context and return the response."""
    api_client = _get_client()

    messages = []
    if history:
        for h in history:
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    response = await api_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        system=_build_system_prompt(drawing),
        messages=messages,
    )

    return response.content[0].text
