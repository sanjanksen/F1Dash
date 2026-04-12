# F1 Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a full-stack F1 Dashboard with a React+Vite frontend (Stats View + Chat View) and a Python FastAPI backend that serves F1 data via FastF1 and answers natural language questions via the Anthropic Claude API.

**Architecture:** The backend (`/server`) exposes four REST endpoints that pull F1 data from FastF1 (session/event data) and the Jolpica-Ergast API (standings/results). The frontend (`/client`) is a Vite React SPA with a tab-based UI; in dev, Vite's proxy forwards `/api` calls to `localhost:8000` so CORS is only needed for production builds (backend still sets CORS headers).

**Tech Stack:** React 19, Vite 8, FastAPI, FastF1 3.x, Anthropic Python SDK, python-dotenv, requests, pytest

---

## File Structure

```
F1Dash/
├── client/                         # React + Vite frontend
│   ├── index.html                  # includes Google Fonts (Barlow Condensed + Plus Jakarta Sans)
│   ├── package.json
│   ├── vite.config.js              # proxy /api → localhost:8000
│   └── src/
│       ├── main.jsx
│       ├── App.jsx                 # tab state, layout shell
│       ├── index.css               # global light theme + design tokens
│       ├── App.css                 # layout, header, all component styles
│       ├── components/
│       │   ├── TabBar.jsx          # pill-style Stats / Chat tab switcher
│       │   ├── StatsView.jsx       # search + results container
│       │   ├── DriverCard.jsx      # editorial driver stats card
│       │   ├── CircuitList.jsx     # season circuit grid
│       │   └── ChatView.jsx        # chat messages + input
│       └── api/
│           └── f1api.js            # fetch wrappers for all endpoints
├── server/
│   ├── main.py                     # FastAPI app, CORS, route wiring
│   ├── f1_data.py                  # FastF1 + Jolpica data functions
│   ├── chat.py                     # Anthropic message builder
│   ├── requirements.txt
│   ├── cache/                      # FastF1 disk cache (git-ignored)
│   └── tests/
│       ├── conftest.py
│       ├── test_f1_data.py
│       ├── test_chat.py
│       └── test_main.py
├── .env                            # ANTHROPIC_API_KEY (git-ignored)
├── .gitignore
└── README.md
```

---

## Task 1: Project Scaffold

**Files:**
- Create: `client/` directory tree (package.json, vite.config.js, index.html, src stubs)
- Create: `server/requirements.txt`, `server/cache/.gitkeep`, `server/tests/conftest.py`
- Create: `.env`, `.gitignore`

- [ ] **Step 1: Create the client directory and package.json**

```bash
mkdir -p client/src/components client/src/api client/public
```

Create `client/package.json`:
```json
{
  "name": "f1dash-client",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^19.2.4",
    "react-dom": "^19.2.4"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^6.0.1",
    "vite": "^8.0.4"
  }
}
```

- [ ] **Step 2: Create client/vite.config.js with API proxy**

```js
// client/vite.config.js
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      }
    }
  }
})
```

- [ ] **Step 3: Create client/index.html (with Google Fonts)**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <link rel="icon" type="image/svg+xml" href="/vite.svg" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>F1 Dashboard</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@600;700;800;900&family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap"
      rel="stylesheet"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create stub entry files in client/src/**

Create `client/src/main.jsx`:
```jsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.jsx'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
```

Create a placeholder `client/src/App.jsx` (will be replaced in Task 5):
```jsx
export default function App() {
  return <div>F1 Dashboard - coming soon</div>
}
```

- [ ] **Step 5: Create server/requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.6
fastf1==3.4.0
anthropic==0.34.0
python-dotenv==1.0.1
requests==2.32.3
pytest==8.3.3
httpx==0.27.2
pytest-asyncio==0.24.0
```

- [ ] **Step 6: Create server directory structure and cache placeholder**

```bash
mkdir -p server/tests server/cache
touch server/cache/.gitkeep
touch server/__init__.py server/tests/__init__.py
```

- [ ] **Step 7: Create server/tests/conftest.py**

```python
# server/tests/conftest.py
import pytest
import sys
import os

# Ensure server/ is on the path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
```

- [ ] **Step 8: Create root .env and update .gitignore**

Create `.env` at project root:
```
ANTHROPIC_API_KEY=your_key_here
```

Create/update `.gitignore`:
```
# Python
server/cache/
server/__pycache__/
server/**/__pycache__/
*.pyc
.pytest_cache/

# Env
.env

# Node
client/node_modules/
node_modules/
client/dist/

# IDE
.vscode/
.idea/
```

- [ ] **Step 9: Install client dependencies**

```bash
cd client && npm install
```

Expected: `node_modules/` created under `client/`.

- [ ] **Step 10: Install Python dependencies**

```bash
cd server && pip install -r requirements.txt
```

Expected: All packages install without error.

- [ ] **Step 11: Commit scaffold**

```bash
git add client/ server/ .env .gitignore
git commit -m "feat: scaffold client/ and server/ directories"
```

---

## Task 2: Backend — FastAPI App + CORS

**Files:**
- Create: `server/main.py`
- Create: `server/tests/test_main.py`

- [ ] **Step 1: Write the failing test for the health check**

Create `server/tests/test_main.py`:
```python
# server/tests/test_main.py
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch

# We patch data functions so main.py loads without real FastF1 network calls
with patch('f1_data.fastf1'), patch('f1_data.requests'):
    from main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_cors_header_present():
    response = client.options(
        "/api/drivers",
        headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"},
    )
    assert response.headers.get("access-control-allow-origin") in (
        "http://localhost:5173", "*"
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd server && python -m pytest tests/test_main.py -v
```

Expected: `ModuleNotFoundError: No module named 'main'` or similar — confirms the test is wired up but nothing exists yet.

- [ ] **Step 3: Write minimal main.py to make tests pass**

Create `server/main.py`:
```python
# server/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

from f1_data import get_drivers, get_driver_stats, get_circuits, get_f1_context
from chat import answer_f1_question

app = FastAPI(title="F1 Dashboard API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:4173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/drivers")
async def drivers_endpoint():
    try:
        return get_drivers()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/driver/{name}/stats")
async def driver_stats_endpoint(name: str):
    stats = get_driver_stats(name)
    if stats is None:
        raise HTTPException(status_code=404, detail=f"Driver '{name}' not found")
    return stats


@app.get("/api/circuits")
async def circuits_endpoint():
    try:
        return get_circuits()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        context = get_f1_context(request.message)
        response = answer_f1_question(request.message, context)
        return {"response": response}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

The test imports reference `f1_data` and `chat` — create empty stubs so the import doesn't fail during this task:

Create `server/f1_data.py` (stub):
```python
import fastf1
import requests

def get_drivers(): return []
def get_driver_stats(name): return None
def get_circuits(): return []
def get_f1_context(message): return ""
```

Create `server/chat.py` (stub):
```python
def answer_f1_question(message, context): return ""
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && python -m pytest tests/test_main.py -v
```

Expected: Both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/main.py server/f1_data.py server/chat.py server/tests/test_main.py
git commit -m "feat: FastAPI app with CORS, health check, and stubbed routes"
```

---

## Task 3: Backend — F1 Data Layer

**Files:**
- Modify: `server/f1_data.py` (replace stub)
- Create: `server/tests/test_f1_data.py`

The data strategy:
- **Jolpica-Ergast API** (`https://api.jolpi.ca/ergast/f1`) for standings, race results (Ergast was retired; Jolpica is the maintained mirror).
- **FastF1** (`fastf1.get_event_schedule`) for the season circuit schedule.

- [ ] **Step 1: Write failing tests for get_drivers**

Create `server/tests/test_f1_data.py`:
```python
# server/tests/test_f1_data.py
import pytest
from unittest.mock import patch, MagicMock


def _make_standings_response():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "StandingsTable": {
                "StandingsLists": [{
                    "DriverStandings": [
                        {
                            "position": "1",
                            "points": "120",
                            "wins": "3",
                            "Driver": {
                                "driverId": "verstappen",
                                "givenName": "Max",
                                "familyName": "Verstappen",
                                "code": "VER",
                                "nationality": "Dutch",
                            },
                            "Constructors": [{"name": "Red Bull Racing"}],
                        },
                        {
                            "position": "2",
                            "points": "95",
                            "wins": "1",
                            "Driver": {
                                "driverId": "norris",
                                "givenName": "Lando",
                                "familyName": "Norris",
                                "code": "NOR",
                                "nationality": "British",
                            },
                            "Constructors": [{"name": "McLaren"}],
                        },
                    ]
                }]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def test_get_drivers_returns_list_of_dicts():
    with patch('f1_data.requests.get', return_value=_make_standings_response()):
        import importlib, f1_data
        importlib.reload(f1_data)
        result = f1_data.get_drivers()

    assert isinstance(result, list)
    assert len(result) == 2
    assert result[0]['full_name'] == 'Max Verstappen'
    assert result[0]['code'] == 'VER'
    assert result[0]['standing'] == 1
    assert result[0]['wins'] == 3
    assert result[0]['team'] == 'Red Bull Racing'


def test_get_drivers_empty_standings():
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {"StandingsTable": {"StandingsLists": []}}
    }
    mock.raise_for_status.return_value = None

    with patch('f1_data.requests.get', return_value=mock):
        import importlib, f1_data
        importlib.reload(f1_data)
        result = f1_data.get_drivers()

    assert result == []


def _make_results_response(driver_id='verstappen'):
    mock = MagicMock()
    mock.json.return_value = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "raceName": "Bahrain Grand Prix",
                        "Results": [{
                            "position": "1",
                            "points": "25",
                            "FastestLap": {"rank": "1"},
                            "Driver": {"driverId": driver_id},
                        }]
                    },
                    {
                        "raceName": "Saudi Arabian Grand Prix",
                        "Results": [{
                            "position": "3",
                            "points": "15",
                            "Driver": {"driverId": driver_id},
                        }]
                    },
                ]
            }
        }
    }
    mock.raise_for_status.return_value = None
    return mock


def test_get_driver_stats_wins_podiums():
    standings_mock = _make_standings_response()
    results_mock = _make_results_response('verstappen')

    with patch('f1_data.requests.get', side_effect=[standings_mock, results_mock]):
        import importlib, f1_data
        importlib.reload(f1_data)
        result = f1_data.get_driver_stats('verstappen')

    assert result is not None
    assert result['wins'] == 1
    assert result['podiums'] == 2
    assert result['fastest_laps'] == 1
    assert result['championship_position'] == 1
    assert len(result['recent_races']) == 2


def test_get_driver_stats_not_found():
    standings_mock = _make_standings_response()

    with patch('f1_data.requests.get', return_value=standings_mock):
        import importlib, f1_data
        importlib.reload(f1_data)
        result = f1_data.get_driver_stats('nobody')

    assert result is None


def test_get_circuits_returns_list():
    import pandas as pd

    mock_schedule = pd.DataFrame([
        {
            'RoundNumber': 1,
            'EventName': 'Bahrain Grand Prix',
            'Location': 'Sakhir',
            'Country': 'Bahrain',
            'EventDate': pd.Timestamp('2025-03-02'),
        }
    ])

    with patch('f1_data.fastf1.get_event_schedule', return_value=mock_schedule):
        import importlib, f1_data
        importlib.reload(f1_data)
        result = f1_data.get_circuits()

    assert len(result) == 1
    assert result[0]['event_name'] == 'Bahrain Grand Prix'
    assert result[0]['round'] == 1
    assert result[0]['country'] == 'Bahrain'
    assert result[0]['date'] == '2025-03-02'
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && python -m pytest tests/test_f1_data.py -v
```

Expected: Multiple FAILUREs — stubs return empty data.

- [ ] **Step 3: Implement f1_data.py**

Replace `server/f1_data.py` entirely:
```python
# server/f1_data.py
import os
import fastf1
import requests

# Enable FastF1 disk cache
_CACHE_DIR = os.path.join(os.path.dirname(__file__), 'cache')
os.makedirs(_CACHE_DIR, exist_ok=True)
fastf1.Cache.enable_cache(_CACHE_DIR)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
CURRENT_YEAR = 2025


def get_drivers() -> list[dict]:
    """Return all drivers in the current season with championship standings."""
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/driverStandings.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    standings_lists = data["MRData"]["StandingsTable"]["StandingsLists"]
    if not standings_lists:
        return []

    drivers = []
    for entry in standings_lists[0]["DriverStandings"]:
        d = entry["Driver"]
        constructors = entry.get("Constructors", [{}])
        drivers.append({
            "driver_id": d["driverId"],
            "full_name": f"{d['givenName']} {d['familyName']}",
            "code": d.get("code", ""),
            "nationality": d.get("nationality", ""),
            "team": constructors[0].get("name", "") if constructors else "",
            "standing": int(entry["position"]),
            "points": float(entry["points"]),
            "wins": int(entry["wins"]),
        })
    return drivers


def get_driver_stats(driver_name: str) -> dict | None:
    """Return wins, podiums, fastest laps, recent races for a driver."""
    # Resolve driver_id from standings
    all_drivers = get_drivers()
    matched = None
    needle = driver_name.lower()
    for d in all_drivers:
        if (
            needle in d["full_name"].lower()
            or needle == d["driver_id"].lower()
            or needle == d["code"].lower()
        ):
            matched = d
            break

    if matched is None:
        return None

    driver_id = matched["driver_id"]

    # Fetch all race results for this driver this season
    resp = requests.get(
        f"{JOLPICA_BASE}/{CURRENT_YEAR}/drivers/{driver_id}/results.json?limit=30",
        timeout=15,
    )
    resp.raise_for_status()
    races = resp.json()["MRData"]["RaceTable"]["Races"]

    wins = 0
    podiums = 0
    fastest_laps = 0
    recent_races = []

    for race in races:
        results = race.get("Results", [])
        if not results:
            continue
        r = results[0]
        pos_str = r.get("position", "0")
        pos = int(pos_str) if pos_str.isdigit() else 0
        points = float(r.get("points", 0))

        if pos == 1:
            wins += 1
        if 1 <= pos <= 3:
            podiums += 1

        fl = r.get("FastestLap", {})
        if fl.get("rank") == "1":
            fastest_laps += 1

        recent_races.append({
            "race": race.get("raceName", ""),
            "position": pos,
            "points": points,
            "fastest_lap": fl.get("rank") == "1",
        })

    return {
        "driver": matched["full_name"],
        "code": matched["code"],
        "team": matched["team"],
        "nationality": matched["nationality"],
        "wins": wins,
        "podiums": podiums,
        "fastest_laps": fastest_laps,
        "championship_position": matched["standing"],
        "points": matched["points"],
        "recent_races": recent_races[-5:],
    }


def get_circuits() -> list[dict]:
    """Return the full season race schedule."""
    schedule = fastf1.get_event_schedule(CURRENT_YEAR, include_testing=False)
    circuits = []
    for _, event in schedule.iterrows():
        circuits.append({
            "round": int(event["RoundNumber"]),
            "event_name": event["EventName"],
            "circuit_name": event["Location"],
            "country": event["Country"],
            "date": str(event["EventDate"].date()),
        })
    return circuits


def get_f1_context(message: str) -> str:
    """Build a concise F1 data context string for the chat endpoint."""
    parts: list[str] = []

    try:
        drivers = get_drivers()
        lines = [f"  {d['standing']}. {d['full_name']} ({d['team']}) — {d['points']} pts, {d['wins']} wins"
                 for d in drivers[:10]]
        parts.append("=== 2025 Driver Championship Standings (Top 10) ===\n" + "\n".join(lines))
    except Exception as exc:
        parts.append(f"[Standings unavailable: {exc}]")

    try:
        circuits = get_circuits()
        upcoming = [c for c in circuits if c["date"] >= "2025-04-11"][:3]
        lines = [f"  Round {c['round']}: {c['event_name']} ({c['country']}) — {c['date']}"
                 for c in upcoming]
        parts.append("=== Upcoming Races ===\n" + "\n".join(lines))
    except Exception as exc:
        parts.append(f"[Schedule unavailable: {exc}]")

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && python -m pytest tests/test_f1_data.py -v
```

Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add server/f1_data.py server/tests/test_f1_data.py
git commit -m "feat: F1 data layer — drivers, driver stats, circuits, chat context"
```

---

## Task 4: Backend — Chat Endpoint (Anthropic)

**Files:**
- Modify: `server/chat.py` (replace stub)
- Create: `server/tests/test_chat.py`
- Modify: `server/tests/test_main.py` (add chat route test)

- [ ] **Step 1: Write failing tests for chat module**

Create `server/tests/test_chat.py`:
```python
# server/tests/test_chat.py
from unittest.mock import patch, MagicMock


def _make_anthropic_response(text="Great question about F1!"):
    mock_resp = MagicMock()
    mock_resp.content = [MagicMock(text=text)]
    return mock_resp


def test_answer_f1_question_calls_claude():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response("Verstappen leads by 25 points.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import importlib, chat
        importlib.reload(chat)
        result = chat.answer_f1_question(
            message="Who leads the championship?",
            f1_context="=== Standings ===\n  1. Max Verstappen — 120 pts",
        )

    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-sonnet-4-20250514"
    assert call_kwargs["max_tokens"] >= 512
    messages = call_kwargs["messages"]
    assert messages[0]["role"] == "user"
    assert "Who leads the championship?" in messages[0]["content"]
    assert "Verstappen" in messages[0]["content"]

    assert result == "Verstappen leads by 25 points."


def test_answer_f1_question_embeds_context_in_prompt():
    mock_client = MagicMock()
    mock_client.messages.create.return_value = _make_anthropic_response("Norris is close.")

    with patch('chat.anthropic.Anthropic', return_value=mock_client):
        import importlib, chat
        importlib.reload(chat)
        chat.answer_f1_question("How is Norris doing?", "Context: Norris P2")

    content = mock_client.messages.create.call_args.kwargs["messages"][0]["content"]
    assert "Context: Norris P2" in content
    assert "How is Norris doing?" in content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && python -m pytest tests/test_chat.py -v
```

Expected: FAIL — stubs return empty strings.

- [ ] **Step 3: Implement chat.py**

Replace `server/chat.py` entirely:
```python
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
```

- [ ] **Step 4: Add the POST /api/chat route test to test_main.py**

Append to `server/tests/test_main.py`:
```python
def test_chat_endpoint_returns_response():
    with patch('f1_data.get_f1_context', return_value="standings data"), \
         patch('chat.answer_f1_question', return_value="Verstappen leads."):
        response = client.post("/api/chat", json={"message": "Who is leading?"})

    assert response.status_code == 200
    assert response.json() == {"response": "Verstappen leads."}


def test_chat_endpoint_rejects_empty_message():
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
```

- [ ] **Step 5: Run all server tests**

```bash
cd server && python -m pytest tests/ -v
```

Expected: All tests PASS.

- [ ] **Step 6: Smoke-test the server manually**

```bash
cd server && uvicorn main:app --reload --port 8000
```

In a second terminal:
```bash
curl http://localhost:8000/health
# Expected: {"status":"ok"}

curl http://localhost:8000/api/drivers | python -m json.tool | head -30
# Expected: JSON array of driver objects
```

- [ ] **Step 7: Commit**

```bash
git add server/chat.py server/tests/test_chat.py server/tests/test_main.py
git commit -m "feat: Anthropic chat endpoint — builds context-aware F1 prompt"
```

---

## Task 5: Frontend — Light Theme, Design Tokens, Layout Shell

**Design direction:** Light editorial — warm off-white background, `Barlow Condensed` for all numeric/display content, `Plus Jakarta Sans` for body text. F1 red used as a precise accent only. Cards are white with soft shadows. The feel is a premium sports magazine, not a dark widget panel.

**Files:**
- Modify: `client/src/index.css` (global design tokens + theme)
- Modify: `client/src/App.jsx` (tab shell)
- Create: `client/src/components/TabBar.jsx`
- Modify: `client/src/App.css`

- [ ] **Step 1: Install client deps and verify dev server starts**

```bash
cd client && npm install && npm run dev
```

Expected: Vite starts on `http://localhost:5173`. Visit the URL — you see "F1 Dashboard - coming soon". Stop the server (`Ctrl+C`).

- [ ] **Step 2: Write global CSS tokens and light theme in client/src/index.css**

Replace `client/src/index.css` entirely:
```css
/* client/src/index.css */
*, *::before, *::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  /* Surfaces */
  --bg: #F6F6F4;
  --surface: #FFFFFF;
  --surface-subtle: #FAFAF8;

  /* Text */
  --text-primary: #161616;
  --text-secondary: #5F5F5F;
  --text-muted: #ABABAB;

  /* Accent */
  --accent: #E10600;
  --accent-hover: #C70000;
  --accent-dim: rgba(225, 6, 0, 0.08);

  /* Borders */
  --border: #EAEAEA;
  --border-strong: #D0D0D0;

  /* Medals */
  --gold: #C9A227;
  --silver: #8A9BA8;
  --bronze: #A0674A;

  /* Radii */
  --radius-sm: 6px;
  --radius: 12px;
  --radius-lg: 18px;

  /* Shadows */
  --shadow-xs: 0 1px 2px rgba(0,0,0,0.04);
  --shadow-sm: 0 1px 4px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03);
  --shadow: 0 2px 10px rgba(0,0,0,0.07), 0 1px 3px rgba(0,0,0,0.04);
  --shadow-lg: 0 8px 32px rgba(0,0,0,0.09), 0 2px 8px rgba(0,0,0,0.05);

  /* Typography */
  --font-display: 'Barlow Condensed', sans-serif;
  --font-body: 'Plus Jakarta Sans', sans-serif;
}

body {
  background: var(--bg);
  color: var(--text-primary);
  font-family: var(--font-body);
  min-height: 100vh;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

#root {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

/* Scrollbar */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border-strong); border-radius: 3px; }

/* Utility classes */
.card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  box-shadow: var(--shadow-sm);
}

.section-label {
  font-family: var(--font-body);
  font-size: 0.68rem;
  font-weight: 600;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

/* Shared entrance animation */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(12px); }
  to   { opacity: 1; transform: translateY(0); }
}

.animate-in {
  animation: fadeUp 0.38s cubic-bezier(0.22, 1, 0.36, 1) both;
}
```

- [ ] **Step 3: Create client/src/components/TabBar.jsx**

```jsx
// client/src/components/TabBar.jsx
export default function TabBar({ activeTab, onTabChange }) {
  const tabs = ['Stats', 'Chat']
  return (
    <div className="header-tabs">
      {tabs.map(tab => (
        <button
          key={tab}
          className={`tab-btn${activeTab === tab ? ' active' : ''}`}
          onClick={() => onTabChange(tab)}
        >
          {tab}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 4: Replace client/src/App.jsx with the full layout shell**

```jsx
// client/src/App.jsx
import { useState } from 'react'
import TabBar from './components/TabBar.jsx'
import StatsView from './components/StatsView.jsx'
import ChatView from './components/ChatView.jsx'
import './App.css'

export default function App() {
  const [activeTab, setActiveTab] = useState('Stats')

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="f1-wordmark">F<span>1</span></span>
            <span className="header-subtitle">Dashboard</span>
          </div>
          <TabBar activeTab={activeTab} onTabChange={setActiveTab} />
        </div>
      </header>
      <main className="app-main">
        {activeTab === 'Stats' ? <StatsView /> : <ChatView />}
      </main>
    </div>
  )
}
```

- [ ] **Step 5: Write client/src/App.css — layout and header**

Replace `client/src/App.css` entirely:
```css
/* client/src/App.css */

/* ─── Shell & Header ─────────────────────────────────────── */
.app-shell {
  display: flex;
  flex-direction: column;
  min-height: 100vh;
}

.app-header {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  position: sticky;
  top: 0;
  z-index: 100;
}

.header-inner {
  max-width: 1140px;
  margin: 0 auto;
  padding: 0 2rem;
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 60px;
  gap: 1.5rem;
}

.header-brand {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-shrink: 0;
}

.f1-wordmark {
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 1.55rem;
  line-height: 1;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.f1-wordmark span { color: var(--accent); }

.header-subtitle {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.18em;
  text-transform: uppercase;
  color: var(--text-muted);
}

/* Pill-style tabs */
.header-tabs {
  display: flex;
  gap: 0.3rem;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 3px;
}

.tab-btn {
  background: transparent;
  border: none;
  border-radius: 7px;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-body);
  font-size: 0.8rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  padding: 0.4rem 1.1rem;
  transition: background 0.15s, color 0.15s, box-shadow 0.15s;
}

.tab-btn.active {
  background: var(--surface);
  color: var(--text-primary);
  box-shadow: var(--shadow-xs);
}

.tab-btn:hover:not(.active) { color: var(--text-primary); }

/* ─── Main content area ───────────────────────────────────── */
.app-main {
  flex: 1;
  max-width: 1140px;
  margin: 0 auto;
  width: 100%;
  padding: 2.5rem 2rem;
}

@media (max-width: 640px) {
  .header-inner  { padding: 0 1rem; }
  .header-subtitle { display: none; }
  .app-main { padding: 1.5rem 1rem; }
}
```

- [ ] **Step 6: Create placeholder StatsView and ChatView so App renders**

Create `client/src/components/StatsView.jsx` (placeholder):
```jsx
export default function StatsView() {
  return <p style={{ color: 'var(--text-muted)' }}>Stats View — coming soon</p>
}
```

Create `client/src/components/ChatView.jsx` (placeholder):
```jsx
export default function ChatView() {
  return <p style={{ color: 'var(--text-muted)' }}>Chat View — coming soon</p>
}
```

- [ ] **Step 7: Verify in browser**

```bash
cd client && npm run dev
```

Open `http://localhost:5173`. Verify:
- Warm off-white background, white header with 1px border
- `F1` wordmark with red `1`, `DASHBOARD` label beside it in small caps
- Two pill tabs: `Stats` and `Chat` — active tab has white pill + shadow
- Clicking tabs switches between placeholder text
- No console errors

Stop server.

- [ ] **Step 8: Commit**

```bash
git add client/src/
git commit -m "feat: frontend shell — light editorial theme, pill tabs, F1 branding"
```

---

## Task 6: Frontend — API Client + Stats View

**Files:**
- Create: `client/src/api/f1api.js`
- Modify: `client/src/components/StatsView.jsx` (full implementation)
- Create: `client/src/components/DriverCard.jsx`
- Create: `client/src/components/CircuitList.jsx`
- Modify: `client/src/App.css` (append component styles)

- [ ] **Step 1: Create client/src/api/f1api.js**

```js
// client/src/api/f1api.js
const BASE = '/api'

async function apiFetch(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }))
    throw new Error(err.detail || `HTTP ${res.status}`)
  }
  return res.json()
}

export const fetchDrivers = () => apiFetch('/drivers')
export const fetchDriverStats = (name) => apiFetch(`/driver/${encodeURIComponent(name)}/stats`)
export const fetchCircuits = () => apiFetch('/circuits')
export const sendChatMessage = (message) =>
  apiFetch('/chat', { method: 'POST', body: JSON.stringify({ message }) })
```

- [ ] **Step 2: Create client/src/components/DriverCard.jsx**

The card features: a giant ghosted championship position number as a background watermark, count-up animations on stat numbers, medal-colored position indicators, and a clean recent-races list.

```jsx
// client/src/components/DriverCard.jsx
import { useEffect, useRef } from 'react'

// Animates a number from 0 to `value` over `duration`ms
function useCountUp(value, duration = 750) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const to = Number(value) || 0
    const start = performance.now()
    const step = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)   // ease-out-cubic
      el.textContent = Math.round(to * eased)
      if (t < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [value, duration])
  return ref
}

const POS_COLOR = { 1: 'var(--gold)', 2: 'var(--silver)', 3: 'var(--bronze)' }

export default function DriverCard({ stats }) {
  if (!stats) return null
  const pos = stats.championship_position
  const posColor = POS_COLOR[pos] ?? 'var(--text-muted)'

  const winsRef     = useCountUp(stats.wins)
  const podiumsRef  = useCountUp(stats.podiums)
  const fastestRef  = useCountUp(stats.fastest_laps)

  return (
    <div className="driver-card card animate-in">
      {/* Decorative watermark — large position number */}
      <div className="driver-watermark" aria-hidden="true">{pos}</div>

      <div className="driver-header">
        <div className="driver-info">
          <span className="driver-code">{stats.code}</span>
          <h2 className="driver-name">{stats.driver}</h2>
          <span className="driver-team">{stats.team}</span>
        </div>
        <div className="driver-pos-block">
          <span className="pos-letter">P</span>
          <span className="pos-number" style={{ color: posColor }}>{pos}</span>
          <span className="pos-pts">{stats.points} pts</span>
        </div>
      </div>

      <div className="stats-grid">
        <StatCell label="Wins"         ref={winsRef}    accent />
        <StatCell label="Podiums"      ref={podiumsRef} />
        <StatCell label="Fastest Laps" ref={fastestRef} />
        <div className="stat-cell plain">
          <span className="stat-num">{stats.nationality?.slice(0, 3).toUpperCase() ?? '—'}</span>
          <span className="stat-label">Origin</span>
        </div>
      </div>

      {stats.recent_races?.length > 0 && (
        <div className="recent-races">
          <p className="section-label" style={{ marginBottom: '0.75rem' }}>Recent Races</p>
          {stats.recent_races.map((race, i) => {
            const rColor = POS_COLOR[race.position] ?? 'var(--text-primary)'
            return (
              <div
                key={i}
                className="race-row animate-in"
                style={{ animationDelay: `${0.08 + i * 0.05}s` }}
              >
                <span className="race-name">{race.race}</span>
                <div className="race-meta">
                  {race.fastest_lap && <span className="fl-tag">FL</span>}
                  <span className="race-pos" style={{ color: rColor }}>P{race.position}</span>
                  <span className="race-pts">{race.points}p</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// forwardRef-style: pass ref via `ref` prop name is not needed here;
// we use a custom prop name to keep things simple.
function StatCell({ label, ref: _, accent, ...props }) {
  const numRef = useRef(null)
  return (
    <div className="stat-cell" {...props}>
      <span
        className="stat-num"
        ref={numRef}
        style={accent ? { color: 'var(--accent)' } : {}}
      >
        0
      </span>
      <span className="stat-label">{label}</span>
    </div>
  )
}
```

Wait — the `ref` forwarding above is awkward. Rewrite `StatCell` to receive the ref correctly from `useCountUp`:

```jsx
// client/src/components/DriverCard.jsx
import { useEffect, useRef } from 'react'

function useCountUp(value, duration = 750) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const to = Number(value) || 0
    const start = performance.now()
    const step = (now) => {
      const t = Math.min((now - start) / duration, 1)
      const eased = 1 - Math.pow(1 - t, 3)
      el.textContent = Math.round(to * eased)
      if (t < 1) requestAnimationFrame(step)
    }
    requestAnimationFrame(step)
  }, [value, duration])
  return ref
}

const POS_COLOR = { 1: 'var(--gold)', 2: 'var(--silver)', 3: 'var(--bronze)' }

export default function DriverCard({ stats }) {
  if (!stats) return null
  const pos = stats.championship_position
  const posColor = POS_COLOR[pos] ?? 'var(--text-muted)'

  const winsRef    = useCountUp(stats.wins)
  const podiumsRef = useCountUp(stats.podiums)
  const fastestRef = useCountUp(stats.fastest_laps)

  return (
    <div className="driver-card card animate-in">
      <div className="driver-watermark" aria-hidden="true">{pos}</div>

      <div className="driver-header">
        <div className="driver-info">
          <span className="driver-code">{stats.code}</span>
          <h2 className="driver-name">{stats.driver}</h2>
          <span className="driver-team">{stats.team}</span>
        </div>
        <div className="driver-pos-block">
          <span className="pos-letter">P</span>
          <span className="pos-number" style={{ color: posColor }}>{pos}</span>
          <span className="pos-pts">{stats.points} pts</span>
        </div>
      </div>

      <div className="stats-grid">
        <div className="stat-cell">
          <span className="stat-num" ref={winsRef} style={{ color: 'var(--accent)' }}>0</span>
          <span className="stat-label">Wins</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num" ref={podiumsRef}>0</span>
          <span className="stat-label">Podiums</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num" ref={fastestRef}>0</span>
          <span className="stat-label">Fastest Laps</span>
        </div>
        <div className="stat-cell">
          <span className="stat-num">{stats.nationality?.slice(0, 3).toUpperCase() ?? '—'}</span>
          <span className="stat-label">Origin</span>
        </div>
      </div>

      {stats.recent_races?.length > 0 && (
        <div className="recent-races">
          <p className="section-label" style={{ marginBottom: '0.75rem' }}>Recent Races</p>
          {stats.recent_races.map((race, i) => {
            const rColor = POS_COLOR[race.position] ?? 'var(--text-primary)'
            return (
              <div
                key={i}
                className="race-row animate-in"
                style={{ animationDelay: `${0.08 + i * 0.05}s` }}
              >
                <span className="race-name">{race.race}</span>
                <div className="race-meta">
                  {race.fastest_lap && <span className="fl-tag">FL</span>}
                  <span className="race-pos" style={{ color: rColor }}>P{race.position}</span>
                  <span className="race-pts">{race.points}p</span>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 3: Append DriverCard styles to client/src/App.css**

```css
/* ─── DriverCard ──────────────────────────────────────────── */
.driver-card {
  position: relative;
  overflow: hidden;
  padding: 1.75rem;
  margin-bottom: 1.5rem;
  transition: box-shadow 0.2s, transform 0.2s;
}
.driver-card:hover {
  box-shadow: var(--shadow-lg);
  transform: translateY(-1px);
}

/* Big ghosted position number — decorative background element */
.driver-watermark {
  position: absolute;
  top: -0.75rem;
  right: 1.25rem;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 10rem;
  line-height: 1;
  color: var(--bg);
  pointer-events: none;
  user-select: none;
  letter-spacing: -0.04em;
  z-index: 0;
}

.driver-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  position: relative;
  z-index: 1;
  margin-bottom: 1.5rem;
}

.driver-info { display: flex; flex-direction: column; gap: 0.2rem; }

.driver-code {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 0.72rem;
  letter-spacing: 0.18em;
  color: var(--accent);
}

.driver-name {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 2.4rem;
  line-height: 1;
  letter-spacing: -0.01em;
  color: var(--text-primary);
}

.driver-team {
  font-size: 0.83rem;
  font-weight: 500;
  color: var(--text-secondary);
  margin-top: 0.15rem;
}

.driver-pos-block {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 0.05rem;
  position: relative;
  z-index: 1;
}

.pos-letter {
  font-family: var(--font-display);
  font-size: 0.9rem;
  font-weight: 700;
  color: var(--text-muted);
  line-height: 1;
}

.pos-number {
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 3.2rem;
  line-height: 1;
  letter-spacing: -0.03em;
}

.pos-pts {
  font-size: 0.78rem;
  font-weight: 600;
  color: var(--text-secondary);
}

/* Stats 4-up grid — separated by 1px lines */
.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 1px;
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
  position: relative;
  z-index: 1;
  margin-bottom: 1.5rem;
}

.stat-cell {
  background: var(--surface-subtle, #FAFAF8);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 1rem 0.5rem;
  gap: 0.3rem;
}

.stat-num {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 2.3rem;
  line-height: 1;
  color: var(--text-primary);
  letter-spacing: -0.02em;
}

.stat-label {
  font-size: 0.62rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

/* Recent races */
.recent-races {
  position: relative;
  z-index: 1;
}

.race-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0.6rem 0;
  border-bottom: 1px solid var(--border);
}
.race-row:last-child { border-bottom: none; }

.race-name {
  font-size: 0.875rem;
  font-weight: 500;
  color: var(--text-primary);
}

.race-meta {
  display: flex;
  align-items: center;
  gap: 0.7rem;
}

.fl-tag {
  font-size: 0.6rem;
  font-weight: 800;
  letter-spacing: 0.1em;
  background: var(--accent-dim);
  color: var(--accent);
  border: 1px solid rgba(225, 6, 0, 0.2);
  border-radius: 3px;
  padding: 0.15rem 0.4rem;
}

.race-pos {
  font-family: var(--font-display);
  font-weight: 800;
  font-size: 1rem;
  letter-spacing: 0.02em;
}

.race-pts {
  font-size: 0.78rem;
  font-weight: 500;
  color: var(--text-muted);
  min-width: 28px;
  text-align: right;
}
```

- [ ] **Step 4: Create client/src/components/CircuitList.jsx**

```jsx
// client/src/components/CircuitList.jsx
export default function CircuitList({ circuits }) {
  if (!circuits?.length) return null
  const today = new Date().toISOString().split('T')[0]

  return (
    <div>
      <p className="section-label" style={{ marginBottom: '1rem' }}>
        2025 Season — {circuits.length} Rounds
      </p>
      <div className="circuit-grid">
        {circuits.map((c, i) => {
          const isPast = c.date < today
          return (
            <div
              key={c.round}
              className={`circuit-card card animate-in${isPast ? ' is-past' : ''}`}
              style={{ animationDelay: `${i * 0.035}s` }}
            >
              <span className="circuit-round-num">
                {String(c.round).padStart(2, '0')}
              </span>
              <p className="circuit-event">{c.event_name}</p>
              <p className="circuit-location">{c.circuit_name}</p>
              <div className="circuit-footer">
                <span className="circuit-country">{c.country}</span>
                <span className="circuit-date">
                  {new Date(c.date + 'T12:00:00').toLocaleDateString('en-GB', {
                    day: 'numeric',
                    month: 'short',
                  })}
                </span>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Append CircuitList styles to client/src/App.css**

```css
/* ─── CircuitList ─────────────────────────────────────────── */
.circuit-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(196px, 1fr));
  gap: 0.75rem;
}

.circuit-card {
  padding: 1.1rem 1rem;
  transition: box-shadow 0.18s, transform 0.18s, border-color 0.18s;
  cursor: default;
}
.circuit-card:hover:not(.is-past) {
  box-shadow: var(--shadow);
  transform: translateY(-2px);
  border-color: var(--accent);
}
.circuit-card.is-past { opacity: 0.38; }

/* Large round number as card's leading visual element */
.circuit-round-num {
  display: block;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 3.5rem;
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--bg);
  margin-bottom: 0.5rem;
}

.circuit-event {
  font-size: 0.85rem;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.3;
  margin-bottom: 0.2rem;
}

.circuit-location {
  font-size: 0.77rem;
  color: var(--text-secondary);
  font-weight: 400;
  margin-bottom: 0.75rem;
}

.circuit-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.circuit-country {
  font-size: 0.67rem;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.circuit-date {
  font-family: var(--font-display);
  font-size: 0.8rem;
  font-weight: 700;
  color: var(--accent);
}
```

- [ ] **Step 6: Implement StatsView.jsx**

Replace `client/src/components/StatsView.jsx` entirely:
```jsx
// client/src/components/StatsView.jsx
import { useState, useEffect } from 'react'
import { fetchDriverStats, fetchCircuits } from '../api/f1api.js'
import DriverCard from './DriverCard.jsx'
import CircuitList from './CircuitList.jsx'

export default function StatsView() {
  const [mode, setMode] = useState('driver')
  const [query, setQuery] = useState('')
  const [driverStats, setDriverStats] = useState(null)
  const [circuits, setCircuits] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (mode === 'circuits' && circuits.length === 0) {
      setLoading(true)
      setError('')
      fetchCircuits()
        .then(setCircuits)
        .catch(e => setError(e.message))
        .finally(() => setLoading(false))
    }
  }, [mode])

  const handleSearch = async (e) => {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    setDriverStats(null)
    try {
      setDriverStats(await fetchDriverStats(query.trim()))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="stats-view">
      <div className="mode-bar">
        <button
          className={`mode-pill${mode === 'driver' ? ' active' : ''}`}
          onClick={() => { setMode('driver'); setDriverStats(null); setError('') }}
        >
          Driver Stats
        </button>
        <button
          className={`mode-pill${mode === 'circuits' ? ' active' : ''}`}
          onClick={() => setMode('circuits')}
        >
          Season Calendar
        </button>
      </div>

      {mode === 'driver' && (
        <form className="search-form" onSubmit={handleSearch}>
          <div className="search-wrap">
            <svg className="search-icon" viewBox="0 0 20 20" fill="none" aria-hidden="true">
              <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" strokeWidth="1.5" />
              <path d="M13 13l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
            </svg>
            <input
              className="search-input"
              type="text"
              placeholder="Search driver — name, code, or nationality…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              autoFocus
            />
          </div>
          <button className="search-btn" type="submit" disabled={loading}>
            {loading ? <span className="spinner" /> : 'Search'}
          </button>
        </form>
      )}

      {error && (
        <div className="error-banner animate-in">⚠ {error}</div>
      )}

      {loading && mode === 'circuits' && (
        <p className="loading-hint">Loading calendar…</p>
      )}

      {mode === 'driver' && driverStats && <DriverCard stats={driverStats} />}

      {mode === 'circuits' && !loading && circuits.length > 0 && (
        <CircuitList circuits={circuits} />
      )}

      {mode === 'driver' && !driverStats && !error && !loading && (
        <div className="search-hint animate-in">
          <p className="hint-primary">Search any driver</p>
          <p className="hint-secondary">Try "Verstappen", "NOR", or "norris"</p>
        </div>
      )}
    </div>
  )
}
```

- [ ] **Step 7: Append StatsView styles to client/src/App.css**

```css
/* ─── StatsView ───────────────────────────────────────────── */
.stats-view { display: flex; flex-direction: column; gap: 1.5rem; }

.mode-bar { display: flex; gap: 0.5rem; }

.mode-pill {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 100px;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-body);
  font-size: 0.8rem;
  font-weight: 600;
  padding: 0.42rem 1rem;
  transition: all 0.16s;
}
.mode-pill.active {
  background: var(--text-primary);
  border-color: var(--text-primary);
  color: #fff;
}
.mode-pill:hover:not(.active) {
  border-color: var(--border-strong);
  color: var(--text-primary);
}

.search-form {
  display: flex;
  gap: 0.625rem;
  align-items: center;
}

.search-wrap {
  flex: 1;
  position: relative;
}

.search-icon {
  position: absolute;
  left: 0.875rem;
  top: 50%;
  transform: translateY(-50%);
  width: 16px;
  height: 16px;
  color: var(--text-muted);
  pointer-events: none;
}

.search-input {
  width: 100%;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: var(--radius-sm);
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 0.92rem;
  padding: 0.72rem 1rem 0.72rem 2.6rem;
  outline: none;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.search-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}
.search-input::placeholder { color: var(--text-muted); }

.search-btn {
  background: var(--text-primary);
  border: none;
  border-radius: var(--radius-sm);
  color: #fff;
  cursor: pointer;
  font-family: var(--font-body);
  font-size: 0.85rem;
  font-weight: 600;
  min-width: 84px;
  padding: 0.72rem 1.2rem;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: background 0.16s, transform 0.1s;
}
.search-btn:hover:not(:disabled) { background: #2a2a2a; }
.search-btn:active:not(:disabled) { transform: scale(0.98); }
.search-btn:disabled { opacity: 0.45; cursor: default; }

/* Spinner inside button */
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255,255,255,0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.65s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.error-banner {
  background: #FFF4F4;
  border: 1px solid rgba(225, 6, 0, 0.2);
  border-radius: var(--radius-sm);
  color: var(--accent);
  font-size: 0.875rem;
  font-weight: 500;
  padding: 0.75rem 1rem;
}

.loading-hint { color: var(--text-muted); font-size: 0.88rem; }

.search-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.4rem;
  padding: 4.5rem 0;
  text-align: center;
}
.hint-primary {
  font-family: var(--font-display);
  font-weight: 700;
  font-size: 1.5rem;
  color: var(--text-secondary);
  letter-spacing: -0.01em;
}
.hint-secondary { font-size: 0.85rem; color: var(--text-muted); }
```

- [ ] **Step 8: Verify in browser with backend running**

Start backend: `cd server && uvicorn main:app --reload --port 8000`
Start frontend: `cd client && npm run dev`

Open `http://localhost:5173`. Test:
1. Stats tab → type `Verstappen` → click Search → driver card appears with animated count-up stats, ghosted watermark `1` behind the header, recent races list
2. Click `Season Calendar` → circuit grid loads, future rounds are full opacity, past rounds are dimmed
3. Type an invalid name (e.g. `zzz`) → soft red error banner shown
4. On load there is a centered hint text prompting search

- [ ] **Step 9: Commit**

```bash
git add client/src/
git commit -m "feat: Stats View — driver card with count-up stats, circuit grid, light design"
```

---

## Task 7: Frontend — Chat View

**Files:**
- Modify: `client/src/components/ChatView.jsx` (full implementation)
- Modify: `client/src/App.css` (append chat styles)

**Design:** Very clean. White background. The input lives at the bottom inside a bordered row that focuses with a red ring. User messages are black bubbles with white text; assistant messages are white cards with border. The F1 avatar is a small black square with the wordmark. Suggestion chips appear until the first message is sent.

- [ ] **Step 1: Implement ChatView.jsx**

Replace `client/src/components/ChatView.jsx` entirely:
```jsx
// client/src/components/ChatView.jsx
import { useState, useRef, useEffect } from 'react'
import { sendChatMessage } from '../api/f1api.js'

const SUGGESTIONS = [
  "Who leads the 2025 championship?",
  "How has Verstappen performed this season?",
  "Which races are coming up next?",
  "Compare Norris and Leclerc this season",
]

export default function ChatView() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: "Ask me anything about the 2025 Formula 1 season — driver performance, standings, race results, or circuit comparisons.",
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)
  const inputRef  = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const send = async (text) => {
    const msg = text.trim()
    if (!msg || loading) return

    setMessages(prev => [...prev, { role: 'user', text: msg }])
    setInput('')
    setLoading(true)

    try {
      const { response } = await sendChatMessage(msg)
      setMessages(prev => [...prev, { role: 'assistant', text: response }])
    } catch (e) {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: `Something went wrong: ${e.message}`, isError: true },
      ])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 60)
    }
  }

  const isIntro = messages.length === 1

  return (
    <div className="chat-container">
      {/* Suggestion chips — visible only before the first user message */}
      {isIntro && (
        <div className="chat-intro animate-in">
          <div className="chat-avatar-lg">
            F<span>1</span>
          </div>
          <p className="chat-intro-label">Your F1 Analyst</p>
          <div className="suggestion-chips">
            {SUGGESTIONS.map(s => (
              <button key={s} className="suggestion-chip" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Message list */}
      <div className="chat-messages">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`bubble-row ${msg.role} animate-in`}
            style={{ animationDelay: `${i * 0.025}s` }}
          >
            {msg.role === 'assistant' && (
              <div className="chat-avatar">F<span>1</span></div>
            )}
            <div className={`chat-bubble ${msg.role}${msg.isError ? ' error' : ''}`}>
              {msg.text}
            </div>
          </div>
        ))}

        {loading && (
          <div className="bubble-row assistant animate-in">
            <div className="chat-avatar">F<span>1</span></div>
            <div className="chat-bubble assistant typing">
              <span className="dot" />
              <span className="dot" />
              <span className="dot" />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input row */}
      <form
        className="chat-input-row"
        onSubmit={e => { e.preventDefault(); send(input) }}
      >
        <input
          ref={inputRef}
          className="chat-input"
          type="text"
          placeholder="Ask about any driver, race, or circuit…"
          value={input}
          onChange={e => setInput(e.target.value)}
          disabled={loading}
          autoFocus
        />
        <button
          className="send-btn"
          type="submit"
          disabled={loading || !input.trim()}
          aria-label="Send"
        >
          <svg viewBox="0 0 20 20" fill="none" width="17" height="17">
            <path d="M3 10h14M17 10l-6-6M17 10l-6 6"
              stroke="currentColor" strokeWidth="1.75"
              strokeLinecap="round" strokeLinejoin="round"
            />
          </svg>
        </button>
      </form>
    </div>
  )
}
```

- [ ] **Step 2: Append ChatView styles to client/src/App.css**

```css
/* ─── ChatView ────────────────────────────────────────────── */
.chat-container {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  max-width: 700px;
}

/* Intro state with avatar + suggestions */
.chat-intro {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 0.75rem;
  padding: 2rem 0 0.5rem;
}

.chat-avatar-lg {
  width: 54px;
  height: 54px;
  background: var(--text-primary);
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 1.1rem;
  color: #fff;
  letter-spacing: -0.01em;
}
.chat-avatar-lg span { color: var(--accent); }

.chat-intro-label {
  font-size: 0.78rem;
  font-weight: 600;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.suggestion-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  justify-content: center;
  margin-top: 0.25rem;
}

.suggestion-chip {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 100px;
  color: var(--text-secondary);
  cursor: pointer;
  font-family: var(--font-body);
  font-size: 0.8rem;
  font-weight: 500;
  padding: 0.42rem 0.9rem;
  transition: border-color 0.15s, color 0.15s, background 0.15s;
}
.suggestion-chip:hover {
  border-color: var(--text-primary);
  color: var(--text-primary);
}

/* Messages */
.chat-messages {
  display: flex;
  flex-direction: column;
  gap: 0.875rem;
  max-height: 55vh;
  overflow-y: auto;
  padding-right: 0.25rem;
  scroll-padding-bottom: 1rem;
}

.bubble-row {
  display: flex;
  gap: 0.6rem;
  align-items: flex-end;
}
.bubble-row.user { flex-direction: row-reverse; }

/* Small F1 avatar beside assistant bubbles */
.chat-avatar {
  width: 28px;
  height: 28px;
  background: var(--text-primary);
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: var(--font-display);
  font-weight: 900;
  font-size: 0.6rem;
  color: #fff;
  flex-shrink: 0;
  letter-spacing: -0.01em;
}
.chat-avatar span { color: var(--accent); }

.chat-bubble {
  max-width: 80%;
  padding: 0.75rem 1rem;
  border-radius: 14px;
  font-size: 0.9rem;
  line-height: 1.62;
  white-space: pre-wrap;
}

.chat-bubble.assistant {
  background: var(--surface);
  border: 1px solid var(--border);
  border-bottom-left-radius: 4px;
  color: var(--text-primary);
}

.chat-bubble.user {
  background: var(--text-primary);
  color: #fff;
  border-bottom-right-radius: 4px;
}

.chat-bubble.error {
  background: #FFF4F4;
  border-color: rgba(225, 6, 0, 0.2);
  color: var(--accent);
}

/* Typing indicator */
.typing {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0.875rem 1rem;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-muted);
  animation: blink 1.2s ease-in-out infinite;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes blink {
  0%, 80%, 100% { opacity: 0.2; transform: scale(0.8); }
  40%           { opacity: 1;   transform: scale(1); }
}

/* Input bar */
.chat-input-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: var(--radius);
  padding: 0.45rem 0.45rem 0.45rem 1rem;
  transition: border-color 0.18s, box-shadow 0.18s;
}
.chat-input-row:focus-within {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px var(--accent-dim);
}

.chat-input {
  flex: 1;
  background: transparent;
  border: none;
  outline: none;
  color: var(--text-primary);
  font-family: var(--font-body);
  font-size: 0.92rem;
  padding: 0.3rem 0;
}
.chat-input::placeholder { color: var(--text-muted); }
.chat-input:disabled { opacity: 0.6; }

.send-btn {
  background: var(--text-primary);
  border: none;
  border-radius: 8px;
  color: #fff;
  cursor: pointer;
  width: 36px;
  height: 36px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: background 0.16s, transform 0.1s;
}
.send-btn:hover:not(:disabled) { background: #2a2a2a; }
.send-btn:active:not(:disabled) { transform: scale(0.93); }
.send-btn:disabled { opacity: 0.28; cursor: default; }
```

- [ ] **Step 3: Verify chat in browser**

With both servers running:
1. Switch to Chat tab — intro state shows F1 logo, "Your F1 Analyst" label, four suggestion chips
2. Click a suggestion chip — user bubble appears (black), typing dots appear, then assistant response card appears
3. Type a custom message and press Enter / click send arrow
4. Verify: `chat-input-row` gets red border+glow when focused; send button becomes fully opaque when text is present
5. Stop the backend and send a message — error bubble renders with soft red background

- [ ] **Step 4: Commit**

```bash
git add client/src/components/ChatView.jsx client/src/App.css
git commit -m "feat: Chat View — intro state, black/white bubbles, typing dots, red focus ring"
```

---

## Task 8: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Write README.md**

Replace the existing `README.md` at the project root:
```markdown
# F1 Dashboard

A full-stack Formula 1 Dashboard — browse driver stats and season calendar, or ask natural language questions about the 2025 season.

## Stack

- **Frontend:** React 19 + Vite 8 (in `/client`)
- **Backend:** Python 3.11+ + FastAPI (in `/server`)
- **F1 Data:** [FastF1](https://github.com/theOehrly/Fast-F1) + [Jolpica-Ergast API](https://api.jolpi.ca/)
- **AI Chat:** Anthropic Claude (`claude-sonnet-4-20250514`)

## Prerequisites

- Node.js 20+
- Python 3.11+
- An [Anthropic API key](https://console.anthropic.com/)

## Setup

### 1. Clone and enter the project

```bash
git clone <repo-url>
cd F1Dash
```

### 2. Configure environment variables

Copy the example env and add your key:

```bash
cp .env.example .env
# Edit .env and set ANTHROPIC_API_KEY=sk-ant-...
```

### 3. Install backend dependencies

```bash
cd server
pip install -r requirements.txt
cd ..
```

### 4. Install frontend dependencies

```bash
cd client
npm install
cd ..
```

## Running

Open **two terminals**:

**Terminal 1 — Backend:**
```bash
cd server
uvicorn main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`

**Terminal 2 — Frontend:**
```bash
cd client
npm run dev
```

Open `http://localhost:5173`

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/drivers` | All 2025 drivers with standings |
| GET | `/api/driver/{name}/stats` | Wins, podiums, recent races for a driver |
| GET | `/api/circuits` | 2025 season calendar |
| POST | `/api/chat` | Natural language F1 Q&A via Claude |

### Chat example

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Who is leading the 2025 championship?"}'
```

## Running Tests

```bash
cd server
python -m pytest tests/ -v
```

## Notes

- FastF1 caches session data to `server/cache/` to speed up repeated requests. The first request for a session will be slow.
- The Jolpica-Ergast API is used for standings and race results (the original Ergast API was retired in 2024).
- The chat endpoint fetches current standings and upcoming race context before calling Claude.
```

- [ ] **Step 2: Create .env.example**

Create `.env.example` at project root:
```
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

- [ ] **Step 3: Commit**

```bash
git add README.md .env.example
git commit -m "docs: README with setup, run instructions, and API reference"
```

---

## Self-Review

### Spec Coverage Check

| Requirement | Task |
|---|---|
| React + Vite frontend | Tasks 1, 5 |
| Modern light theme with F1-style red accents | Task 5 |
| Stats View tab | Tasks 5, 6 |
| Chat View tab | Tasks 5, 7 |
| Driver search — wins, podiums, recent races, fastest laps, championship standings | Task 6 |
| Circuit list | Task 6 |
| Chat — natural language Q&A | Task 7 |
| FastAPI backend | Task 2 |
| GET /api/drivers | Tasks 2, 3 |
| GET /api/driver/{name}/stats | Tasks 2, 3 |
| GET /api/circuits | Tasks 2, 3 |
| POST /api/chat | Tasks 2, 4 |
| FastF1 cache enabled | Task 3 |
| Anthropic SDK for chat | Task 4 |
| Frontend in /client, backend in /server | Task 1 |
| .env for ANTHROPIC_API_KEY | Task 1 |
| README with setup/run instructions | Task 8 |
| CORS configured | Task 2 |
| requirements.txt | Task 1 |

All requirements covered.

### Placeholder Scan

No TBDs, TODOs, or "similar to task N" references found. All code blocks contain actual implementation.

### Type Consistency Check

- `get_f1_context` defined in Task 3 (`f1_data.py`), imported in `main.py` (Task 2 stub already has it), used in `chat_endpoint` — consistent.
- `answer_f1_question(message, f1_context)` defined in Task 4 (`chat.py`), called in `main.py` with those exact args — consistent.
- `fetchDriverStats`, `fetchCircuits`, `sendChatMessage` defined in Task 6 (`f1api.js`), imported and called in `StatsView.jsx` (Task 6) and `ChatView.jsx` (Task 7) — consistent.
- `DriverCard` receives `stats` prop with fields `driver`, `team`, `wins`, `podiums`, `fastest_laps`, `championship_position`, `points`, `recent_races` — all populated by `get_driver_stats` return value in Task 3 — consistent.
- CSS classes referenced in JSX (`driver-card`, `stats-grid`, `stat-cell`, `bubble-row`, `chat-bubble`, etc.) are all defined in the App.css append steps in the same task — consistent.
