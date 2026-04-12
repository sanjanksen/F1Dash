# server/chat.py
"""
Agentic chat loop using Anthropic tool use.

Claude calls tools to fetch F1 data dynamically, rather than receiving a
pre-built context string. The loop continues until Claude produces a final
text answer or the MAX_TOOL_ROUNDS safety limit is hit.
"""
import json
import os
import anthropic
from tools import TOOL_DEFINITIONS, execute_tool

_client: anthropic.Anthropic | None = None

MAX_TOOL_ROUNDS = 5

SYSTEM_PROMPT = """You are an expert Formula 1 analyst with access to real-time 2025 season data through tools.

Your job is to answer questions about the 2025 F1 season accurately, using the tools provided to fetch up-to-date data. Do not rely on your training knowledge for current standings, results, or points — always fetch the relevant data first.

Guidelines:
- For championship standings questions: use get_driver_standings or get_constructor_standings
- For questions about a specific driver: use get_driver_season_stats
- For comparing two drivers: use get_head_to_head (it's more efficient than two separate stats calls)
- For questions about a specific race result or winner: use get_race_results with the round number
- For qualifying or pole position questions: use get_qualifying_results
- For calendar or schedule questions: use get_season_schedule
- If you need the round number for a race but don't know it, call get_season_schedule first
- For sector-by-sector pace comparisons: use get_sector_comparison
- For how a driver's pace evolved across laps: use get_driver_lap_times
- For corner-level analysis (braking, throttle, DRS): use get_lap_telemetry
- You may call multiple tools — use as many as needed to give a complete answer
- Be concise and specific. Lead with the key fact, then support with numbers from the data."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        _client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    return _client


def answer_f1_question(message: str) -> str:
    """
    Answer an F1 question using Claude with dynamic tool calls.

    Runs an agentic loop: Claude decides which tools to call, the backend
    executes them, results are fed back, and the process repeats until Claude
    produces a final text answer.

    Raises ValueError if no answer is produced within MAX_TOOL_ROUNDS rounds.
    """
    client = _get_client()
    messages = [{"role": "user", "content": message}]

    for _ in range(MAX_TOOL_ROUNDS):
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        if response.stop_reason == "end_turn":
            for block in response.content:
                if hasattr(block, "text"):
                    return block.text
            raise ValueError("Claude returned end_turn but no text content block")

        if response.stop_reason == "tool_use":
            # Execute all tool calls from this response (may be parallel)
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    result = execute_tool(block.name, block.input)
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result, default=str),
                    })
                except Exception as exc:
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": str(exc),
                        "is_error": True,
                    })

            # Add the assistant's response and all tool results to message history
            messages.append({"role": "assistant", "content": response.content})
            messages.append({"role": "user", "content": tool_results})

        else:
            raise ValueError(f"Unexpected stop_reason from Claude: {response.stop_reason!r}")

    raise ValueError(
        f"Exceeded {MAX_TOOL_ROUNDS} tool-call rounds without a final answer. "
        "The question may require more context than the tools can provide."
    )
