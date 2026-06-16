"""
main.py — FastAPI application entry point.

Wires all components together and manages the application lifespan.
Serves the web UI from /static and exposes a WebSocket at /ws
for real-time campaign status updates and message delivery events.

Run with:
    uvicorn app.main:app --reload
"""

from __future__ import annotations

import asyncio
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import Config
from app.logger import get_logger
from app.db.campaign_store import CampaignStore
from app.services.text_generator import TextGenerator
from app.services.image_generator import ImageGenerator
from app.services.sms_simulator import SMSSimulator
from app.services.scheduler import Scheduler
from app.api.routes import router
from app.api.ws_manager import WebSocketManager

logger = get_logger(__name__)

STATIC_DIR = Path(__file__).parent.parent / "static"


# ---------------------------------------------------------------------------
# Lifespan — startup / shutdown
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("=" * 60)
    logger.info("AI Marketing Automation System — starting up.")
    logger.info("Database  : %s", Config.DB_PATH)
    logger.info("Scheduler interval: %ds", Config.SCHEDULER_INTERVAL_SECONDS)
    logger.info("=" * 60)

    # WebSocket manager — capture the running event loop so the background
    # scheduler thread can safely schedule broadcasts
    ws_manager = WebSocketManager()
    ws_manager.set_event_loop(asyncio.get_running_loop())

    store = CampaignStore(db_path=Config.DB_PATH)
    text_gen = TextGenerator()
    image_gen = ImageGenerator()
    sms_sim = SMSSimulator(ws_manager=ws_manager)

    scheduler = Scheduler(
        store=store,
        text_generator=text_gen,
        image_generator=image_gen,
        sms_simulator=sms_sim,
        interval_seconds=Config.SCHEDULER_INTERVAL_SECONDS,
    )

    app.state.store = store
    app.state.scheduler = scheduler
    app.state.ws_manager = ws_manager

    scheduler.start()
    logger.info("Application startup complete — UI at http://localhost:8000")

    yield

    logger.info("AI Marketing Automation System — shutting down.")
    scheduler.stop()
    logger.info("Shutdown complete.")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="AI Marketing Automation System",
    description="Create and schedule AI-generated marketing campaigns.",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static assets
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Register API routes
app.include_router(router)


# ---------------------------------------------------------------------------
# UI — serve index.html at root
# ---------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
async def serve_ui():
    """Serve the single-page web UI."""
    index = STATIC_DIR / "index.html"
    return FileResponse(str(index))


# ---------------------------------------------------------------------------
# WebSocket — real-time campaign dispatch events
# ---------------------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint — push campaign events to connected browsers."""
    manager: WebSocketManager = websocket.app.state.ws_manager
    await manager.connect(websocket)
    try:
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        manager.disconnect(websocket)


# ---------------------------------------------------------------------------
# Global exception handler
# ---------------------------------------------------------------------------

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    tb = traceback.format_exc()
    logger.error(
        "Unhandled exception on %s %s:\n%s",
        request.method,
        request.url.path,
        tb,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred. Please try again later."},
    )
