# server/chat.py
import os
import anthropic

_client: anthropic.Anthropic | None = None


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def answer_f1_question(message: str, f1_context: str) -> str:
    """Send the user question plus F1 data context to Claude and return the reply."""
    prompt = f"""You are an expert Formula 1 analyst with deep knowledge of driver performance, race strategy, and circuit characteristics.

Use the following real F1 data to give an accurate, insightful answer. Where the data is limited, draw on your general F1 knowledge but be clear about what is data-backed vs. your analysis.

{f1_context}

User question: {message}

Answer concisely and directly. Use specific numbers from the data where available."""

    response = _get_client().messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text
