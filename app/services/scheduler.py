"""
services/scheduler.py — Background campaign dispatch scheduler.

The Scheduler runs in a daemon thread and polls the CampaignStore every
SCHEDULER_INTERVAL_SECONDS for campaigns that are due (status=pending,
schedule_time <= now). Each due campaign is immediately locked to
status=processing before generation begins, preventing duplicate dispatch
across polling cycles.

Lifecycle:
  pending  →  processing  →  sent   (generated_text + image_url stored)
                          →  failed  (on any error during generation/dispatch)
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from app.logger import get_logger

if TYPE_CHECKING:
    from app.db.campaign_store import CampaignStore
    from app.services.image_generator import ImageGenerator
    from app.services.sms_simulator import SMSSimulator
    from app.services.text_generator import TextGenerator

logger = get_logger(__name__)


class Scheduler:
    """Polls for due campaigns and dispatches them automatically."""

    def __init__(
        self,
        store: "CampaignStore",
        text_generator: "TextGenerator",
        image_generator: "ImageGenerator",
        sms_simulator: "SMSSimulator",
        interval_seconds: int = 30,
    ) -> None:
        self._store = store
        self._text_generator = text_generator
        self._image_generator = image_generator
        self._sms_simulator = sms_simulator
        self._interval = max(1, min(interval_seconds, 60))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the scheduler background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("Scheduler is already running — start() ignored.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="CampaignScheduler",
            daemon=True,
        )
        self._thread.start()
        logger.info("Scheduler started — polling every %d second(s).", self._interval)

    def stop(self) -> None:
        """Signal the scheduler to stop after its current sleep cycle."""
        self._stop_event.set()
        logger.info("Scheduler stop requested.")

    # ------------------------------------------------------------------
    # Internal poll loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main scheduler loop — runs until stop() is called."""
        logger.debug("Scheduler thread entered _run().")
        while not self._stop_event.is_set():
            try:
                self._process_due_campaigns()
            except Exception as exc:
                logger.error("Unhandled error in scheduler loop: %s", exc, exc_info=True)

            self._stop_event.wait(timeout=self._interval)

        logger.info("Scheduler thread exiting.")

    def _process_due_campaigns(self) -> None:
        """Fetch and dispatch all currently due campaigns."""
        due = self._store.get_due_campaigns()
        if not due:
            logger.debug("Scheduler poll — no due campaigns.")
            return

        logger.info("Scheduler poll — %d due campaign(s) found.", len(due))

        for campaign in due:
            self._dispatch(campaign)

    def _dispatch(self, campaign) -> None:
        """Dispatch a single campaign through the full generation pipeline.

        Steps:
          1. Lock the campaign to ``processing`` (prevents re-pickup).
          2. Generate marketing text via Groq.
          3. Generate image URL via Pollinations.AI.
          4. Simulate SMS delivery.
          5. Persist generated_text + image_url, mark as ``sent``.
          6. On any error, mark as ``failed``.
        """
        cid = campaign.campaign_id
        stage = "init"
        logger.info("Dispatching campaign id=%d (%r).", cid, campaign.campaign_name)

        try:
            # Step 1 — lock immediately to prevent concurrent re-pickup
            stage = "locking"
            self._store.update_status(cid, "processing")

            # Broadcast processing state to connected UI clients
            self._sms_simulator.broadcast_status(
                campaign_id=cid,
                campaign_name=campaign.campaign_name,
                phone=campaign.phone,
                status="processing",
            )

            # Step 2 — generate text
            stage = "text_generation"
            generated_text = self._text_generator.generate(campaign.prompt)

            # Step 3 — generate image URL
            stage = "image_generation"
            image_url = self._image_generator.generate(campaign.prompt)

            # Step 4 — simulate SMS (console print + WebSocket broadcast)
            stage = "sms_simulation"
            self._sms_simulator.send(campaign, generated_text, image_url)

            # Step 5 — persist results and mark sent atomically
            stage = "saving_result"
            self._store.update_dispatch_result(cid, generated_text, image_url)
            logger.info("Campaign id=%d dispatched successfully.", cid)

        except Exception as exc:
            logger.error(
                "Campaign id=%d FAILED at stage=%r — %s",
                cid,
                stage,
                exc,
                exc_info=True,
            )
            try:
                self._store.update_status(cid, "failed")
                # Notify UI of failure
                self._sms_simulator.broadcast_status(
                    campaign_id=cid,
                    campaign_name=campaign.campaign_name,
                    phone=campaign.phone,
                    status="failed",
                    error=str(exc),
                )
            except Exception as update_exc:
                logger.error(
                    "Could not mark campaign id=%d as failed: %s", cid, update_exc
                )
