# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Backend (run from `server/`):**
```bash
uvicorn main:app --reload --port 8000   # dev server, API docs at :8000/docs
python -m pytest tests/ -v              # all tests
python -m pytest tests/test_chat.py -v # single test file
```

**Frontend (run from `client/`):**
```bash
npm run dev      # Vite dev server at :5173 (proxies /api → :8000)
npm run build
```

**Environment:** Copy `.env.example` → `.env` and set `ANTHROPIC_API_KEY`. Optionally set `LLM_PROVIDER=openai` + `OPENAI_API_KEY` to switch providers.

## Architecture

This is a full-stack agentic F1 analyst. A user's natural-language question triggers an agentic loop on the backend that calls F1 data tools and returns structured text + widgets.

### Request lifecycle

1. `POST /api/chat` → `main.py` → `chat.py:answer_f1_payload()`
2. `resolver.py` extracts F1 entities (drivers, teams, circuits, rounds) — tries Claude Haiku first, falls back to regex
3. `chat.py` runs the agentic loop (max 8 tool rounds): Claude picks tools → tools call `f1_data.py` functions → results feed back into Claude
4. `chat.py` builds typed widget dicts from tool results and assembles the final response
5. `AnswerRenderer.jsx` maps each widget `type` → its React component in `chat-widgets/`

### Backend modules

| File | Role |
|---|---|
| `chat.py` | Agentic loop, widget builders (`_make_*_widget`), system prompts |
| `tools.py` | Tool registry (`TOOL_DEFINITIONS` / `OPENAI_TOOL_DEFINITIONS`), `execute_tool()` dispatcher |
| `f1_data.py` | All F1 data fetching — FastF1 (telemetry, lap times) + Jolpica-Ergast (standings, results) |
| `resolver.py` | Entity extraction; caches driver/circuit lists for 5 min |
| `openf1.py` | OpenF1 API — pit stops, team radio, live intervals |
| `circuit_profiles.py` | Static circuit character knowledge (downforce, energy, sectors) |
| `driver_styles.py` | Static driver style analysis and teammate comparison framing |
| `team_car_profiles.py` | Static team car characteristic knowledge |
| `energy_2026.py` | 2026 hybrid energy management rules knowledge |

### Tool taxonomy (important)

`tools.py` defines two tiers — the model is instructed to prefer composite tools for broad questions:

- **Composite recap tools** (`COMPOSITE_TOOL_DEFINITIONS`): return rich narratives; e.g. `get_driver_race_story`, `analyze_qualifying_battle`, `get_driver_weekend_overview`
- **Primitive tools** (`PRIMITIVE_TOOL_DEFINITIONS`): factual building blocks for focused follow-ups; e.g. `get_lap_telemetry`, `get_race_results`, `get_sector_comparison`

Both lists are merged into `TOOL_DEFINITIONS` (Anthropic format) and `OPENAI_TOOL_DEFINITIONS`.

### Widget system

Each tool result produces a typed widget dict in `chat.py`. Widget types:
`race_story`, `qualifying_battle`, `race_pace_battle`, `circuit_profile`, `energy_management`, `pit_stop_strategy`, `speed_trace`, `track_map`, `corner_comparison`, `data_table`

Adding a new widget requires: (1) a `_make_*_widget()` builder in `chat.py`, (2) a React component in `client/src/components/chat-widgets/`, (3) a case in `AnswerRenderer.jsx`.

### Data caching

- FastF1 session data: disk-cached to `server/cache/` (first request per session is slow)
- Driver/circuit lists in `resolver.py`: in-memory, 5-min TTL
- Tests stub all heavy dependencies (fastf1, anthropic, requests) via `conftest.py`

### Frontend state

- `useChatSessions.js` — all chat session and message state (no external state library)
- `f1api.js` — thin HTTP client; all paths relative to `/api`
- No frontend tests; Vite's `/api` proxy handles dev CORS
