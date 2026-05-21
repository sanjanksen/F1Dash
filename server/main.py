# server/main.py
import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

import logging
logger = logging.getLogger(__name__)

from f1_data import get_drivers, get_driver_stats, get_circuits
from chat import answer_f1_payload, answer_f1_question

app = FastAPI(title="F1 Dashboard API", version="1.0.0")

# ── Editorial ingestion scheduler ─────────────────────────────────────────────
_scheduler = None


def _safe_editorial_ingest():
    try:
        from editorial.rss import poll_rss_feeds, DEFAULT_FEEDS
        from editorial.fia_poller import poll_fia_documents
    except Exception as e:
        logger.warning("Editorial modules unavailable: %s", type(e).__name__)
        return
    try:
        poll_rss_feeds(DEFAULT_FEEDS)
        poll_fia_documents()
    except Exception as e:
        logger.warning("Editorial ingestion run failed: %s", type(e).__name__, exc_info=True)


def _build_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        logger.warning("APScheduler not installed — editorial ingestion disabled.")
        return None
    sched = BackgroundScheduler()
    sched.add_job(_safe_editorial_ingest, "interval", hours=2, id="editorial_ingest")
    return sched


@app.on_event("startup")
async def _start_editorial_scheduler():
    global _scheduler
    if os.getenv("EDITORIAL_INGEST_ENABLED", "true").lower() != "true":
        logger.info("EDITORIAL_INGEST_ENABLED=false — scheduler not started.")
        return
    _scheduler = _build_scheduler()
    if _scheduler is None:
        return
    try:
        _scheduler.start()
        logger.info("Editorial ingestion scheduler started — every 2 hours.")
    except Exception as e:
        logger.warning("Failed to start editorial scheduler: %s", type(e).__name__)


@app.on_event("shutdown")
async def _stop_editorial_scheduler():
    global _scheduler
    if _scheduler is not None and getattr(_scheduler, "running", False):
        try:
            _scheduler.shutdown(wait=False)
        except Exception as e:
            logger.warning("Editorial scheduler shutdown error: %s", type(e).__name__)

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
        logger.warning(
            "Error in GET /api/drivers: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch drivers ({type(e).__name__}).",
        )


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
        logger.warning(
            "Error in GET /api/driver/%s/stats: %s",
            name,
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch driver stats ({type(e).__name__}).",
        )


@app.get("/api/circuits")
async def circuits_endpoint():
    try:
        return get_circuits()
    except Exception as e:
        logger.warning(
            "Error in GET /api/circuits: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch circuit schedule ({type(e).__name__}).",
        )


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    if not request.message.strip():
        raise HTTPException(status_code=400, detail="message cannot be empty")
    try:
        return await run_in_threadpool(answer_f1_payload, request.message, request.history)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning(
            "Error in POST /api/chat: %s",
            type(e).__name__,
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to process chat request ({type(e).__name__}).",
        )
