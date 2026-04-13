# server/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

import logging
logger = logging.getLogger(__name__)

from f1_data import get_drivers, get_driver_stats, get_circuits
from chat import answer_f1_payload, answer_f1_question

app = FastAPI(title="F1 Dashboard API", version="1.0.0")

_cors_env = os.getenv("CORS_ORIGINS", "http://localhost:5173,http://localhost:4173")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: list[dict] = []


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/drivers")
async def drivers_endpoint():
    try:
        return get_drivers()
    except Exception as e:
        logger.exception("Error in GET /api/drivers")
        raise HTTPException(status_code=500, detail="Failed to fetch drivers.")


@app.get("/api/driver/{name}/stats")
async def driver_stats_endpoint(name: str):
    try:
        stats = get_driver_stats(name)
        if stats is None:
            raise HTTPException(status_code=404, detail=f"Driver '{name}' not found")
        return stats
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.exception("Error in GET /api/driver/%s/stats", name)
        raise HTTPException(status_code=500, detail="Failed to fetch driver stats.")


@app.get("/api/circuits")
async def circuits_endpoint():
    try:
        return get_circuits()
    except Exception as e:
        logger.exception("Error in GET /api/circuits")
        raise HTTPException(status_code=500, detail="Failed to fetch circuit schedule.")


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        return answer_f1_payload(request.message, request.history)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.exception("Error in POST /api/chat")
        raise HTTPException(status_code=500, detail="Something went wrong processing your request.")
