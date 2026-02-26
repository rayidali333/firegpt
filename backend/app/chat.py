"""
Chat module — LLM-powered Q&A about parsed drawing data.

The parsed symbol data is tiny (~2-5KB JSON), so we inject it directly
into the system prompt. No RAG or vector DB needed.
"""

import json
import os

from anthropic import AsyncAnthropic

from app.models import ParseResponse

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


def _build_system_prompt(drawing: ParseResponse) -> str:
    """Build a system prompt with the parsed drawing data injected."""
    symbol_data = []
    for s in drawing.symbols:
        entry = {
            "block_name": s.block_name,
            "label": s.label,
            "count": s.count,
        }
        if s.sample_locations:
            entry["sample_locations"] = s.sample_locations
        symbol_data.append(entry)

    data_json = json.dumps(symbol_data, indent=2)

    return f"""You are DrawingIQ, an AI assistant specialized in analyzing construction drawings, \
particularly fire alarm system drawings.

You are helping a fire alarm contractor analyze a drawing file. Below is the extracted symbol data \
from the drawing "{drawing.filename}" ({drawing.file_type.upper()} format).

EXTRACTED SYMBOL DATA:
{data_json}

TOTAL SYMBOLS DETECTED: {drawing.total_symbols}

INSTRUCTIONS:
- Answer questions about symbol counts, types, and locations accurately.
- When asked about counts, use the exact numbers from the data above.
- If asked about a symbol type not in the data, say it was not found in this drawing.
- "block_name" is the technical name from the CAD file. "label" is the human-readable name.
- Help with bid estimation, device scheduling, and material takeoffs.
- Be concise and direct. Fire alarm contractors need quick, accurate answers.
- If the user asks about something outside the drawing data, let them know you can only \
answer questions about the uploaded drawing.
- Format counts and lists clearly using tables when appropriate."""


async def chat_with_drawing(message: str, drawing: ParseResponse) -> str:
    """Send a message to the LLM with drawing context and return the response."""
    api_client = _get_client()

    response = await api_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=_build_system_prompt(drawing),
        messages=[{"role": "user", "content": message}],
    )

    return response.content[0].text
