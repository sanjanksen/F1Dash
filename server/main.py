# server/main.py
import asyncio
import json
import os
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '.env'))

import logging
logger = logging.getLogger(__name__)

from f1_data import get_drivers, get_driver_stats, get_circuits
from chat import answer_f1_payload_streaming

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

    async def event_generator():
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def producer():
            try:
                for chunk in answer_f1_payload_streaming(request.message, request.history):
                    loop.call_soon_threadsafe(queue.put_nowait, chunk)
            except ValueError as exc:
                err = json.dumps({"type": "error", "detail": str(exc)})
                loop.call_soon_threadsafe(queue.put_nowait, f"data: {err}\n\n")
            except Exception as exc:
                logger.exception("Error in POST /api/chat streaming")
                err = json.dumps({"type": "error", "detail": "Something went wrong processing your request."})
                loop.call_soon_threadsafe(queue.put_nowait, f"data: {err}\n\n")
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        loop.run_in_executor(None, producer)

        while True:
            item = await queue.get()
            if item is None:
                break
            yield item

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/admin/rebuild-driver-ratings")
async def rebuild_driver_ratings(background_tasks: BackgroundTasks):
    """
    Trigger an offline rebuild of the Bayesian driver ratings cache.
    Takes 5-15 minutes. Returns immediately; build runs in background.
    """
    from driver_rating import build_and_cache_ratings
    background_tasks.add_task(
        build_and_cache_ratings,
        seasons=[2021, 2022, 2023, 2024, 2025],
        draws=1000, tune=500, chains=2,
    )
    return {"status": "rebuild started", "note": "check server logs; cache updates in ~10 minutes"}
