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
