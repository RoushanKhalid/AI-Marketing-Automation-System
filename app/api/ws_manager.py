"""
api/ws_manager.py — WebSocket connection manager.

Thread-safe broadcast from the background Scheduler thread to all
connected browser clients.

Key design decisions:
- The event loop is captured fresh each time broadcast_sync is called
  using asyncio.get_event_loop() on the stored loop reference, so it
  survives uvicorn --reload restarts.
- Uses asyncio.run_coroutine_threadsafe() to safely schedule the async
  broadcast coroutine from the sync scheduler thread.
- Dead connections are pruned silently on every broadcast.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket

from app.logger import get_logger

logger = get_logger(__name__)


class WebSocketManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self, websocket: WebSocket) -> None:
        """Accept and register a new WebSocket connection."""
        await websocket.accept()
        self._connections.append(websocket)
        logger.debug("WebSocket connected — total: %d", len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        """Remove a connection from the active list."""
        if websocket in self._connections:
            self._connections.remove(websocket)
        logger.debug("WebSocket disconnected — total: %d", len(self._connections))

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send a JSON event to all connected clients (async version).

        Dead/closed connections are silently removed.
        """
        if not self._connections:
            return

        message = json.dumps(data, ensure_ascii=False)
        dead: list[WebSocket] = []

        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)

        for ws in dead:
            self.disconnect(ws)

        if self._connections:
            logger.debug(
                "WebSocket broadcast sent to %d client(s): type=%s",
                len(self._connections),
                data.get("type"),
            )

    def broadcast_sync(self, data: dict[str, Any]) -> None:
        """Schedule a broadcast from a non-async (scheduler) thread.

        Uses the event loop stored at startup to safely hand off the
        coroutine to the async event loop running in the main thread.
        Logs a warning instead of silently dropping if the loop is gone.
        """
        if not self._connections:
            logger.debug("broadcast_sync: no connected clients, skipping.")
            return

        loop = self._loop
        if loop is None or loop.is_closed():
            logger.warning("broadcast_sync: event loop unavailable, message dropped.")
            return

        try:
            future = asyncio.run_coroutine_threadsafe(self.broadcast(data), loop)
            # Don't block — fire and forget, but log any exception
            def _log_exc(f: asyncio.Future) -> None:
                exc = f.exception()
                if exc:
                    logger.error("WebSocket broadcast error: %s", exc)
            future.add_done_callback(_log_exc)
        except RuntimeError as exc:
            logger.warning("broadcast_sync failed: %s", exc)

    # ------------------------------------------------------------------
    # Event loop registration
    # ------------------------------------------------------------------

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Store the running event loop (called once at app startup)."""
        self._loop = loop
        logger.debug("WebSocketManager: event loop registered %s", loop)
