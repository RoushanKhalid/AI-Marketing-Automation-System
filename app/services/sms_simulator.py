"""
services/sms_simulator.py — Console-based SMS delivery simulator.

SMSSimulator prints a formatted marketing message to stdout (spec requirement)
and also broadcasts WebSocket events so the web UI can display phone-mockup
animations and status changes in real time.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.logger import get_logger
from app.models.campaign import CampaignRecord

if TYPE_CHECKING:
    from app.api.ws_manager import WebSocketManager

logger = get_logger(__name__)


class SMSSimulator:
    """Simulates SMS delivery — console output + WebSocket broadcast."""

    def __init__(self, ws_manager: Optional["WebSocketManager"] = None) -> None:
        self._ws_manager = ws_manager

    def send(
        self,
        campaign: CampaignRecord,
        generated_text: str,
        image_url: str,
    ) -> None:
        """Simulate sending a marketing SMS for the given campaign.

        1. Validates inputs.
        2. Prints the exact spec console output format.
        3. Broadcasts a ``message_sent`` WebSocket event for the web UI.
        4. Logs an INFO audit entry.

        Args:
            campaign:       The campaign being dispatched.
            generated_text: AI-generated marketing copy (must be non-empty).
            image_url:      Pollinations.AI image URL (must be non-empty).

        Raises:
            ValueError: If ``generated_text`` or ``image_url`` is None or empty.
        """
        if not generated_text or not generated_text.strip():
            raise ValueError(
                f"Cannot send campaign id={campaign.campaign_id}: "
                "generated_text is empty or None."
            )
        if not image_url or not image_url.strip():
            raise ValueError(
                f"Cannot send campaign id={campaign.campaign_id}: "
                "image_url is empty or None."
            )

        # 1. Console output — exact spec format (ensure single-line text for strict output line counts)
        clean_text = " ".join(generated_text.splitlines()).strip()
        output = (
            f"Sending marketing message to {campaign.phone}\n"
            f"Campaign: {campaign.campaign_name}\n"
            f"Generated Text:\n{clean_text}\n"
            f"Generated Image:\n{image_url}"
        )
        print(output, flush=True)

        # 2. WebSocket broadcast for live UI update
        if self._ws_manager:
            self._ws_manager.broadcast_sync({
                "type": "message_sent",
                "campaign_id": campaign.campaign_id,
                "campaign_name": campaign.campaign_name,
                "phone": campaign.phone,
                "generated_text": generated_text,
                "image_url": image_url,
            })

        # 3. Audit log
        logger.info(
            "SMS simulated — campaign_id=%d | campaign_name=%r | phone=%s",
            campaign.campaign_id,
            campaign.campaign_name,
            campaign.phone,
        )

    def broadcast_status(
        self,
        campaign_id: int,
        campaign_name: str,
        phone: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """Broadcast a status change event to all connected WebSocket clients.

        Used to push ``processing`` and ``failed`` state changes to the UI
        in real time, so the campaign table updates without requiring a poll.

        Args:
            campaign_id:   The campaign whose status changed.
            campaign_name: Human-readable campaign name.
            phone:         Target phone number.
            status:        New status value (``processing`` or ``failed``).
            error:         Optional error message for ``failed`` events.
        """
        if self._ws_manager is None:
            return

        payload: dict = {
            "type": "status_update",
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "phone": phone,
            "status": status,
        }
        if error:
            payload["error"] = error

        self._ws_manager.broadcast_sync(payload)
        logger.debug(
            "broadcast_status — campaign_id=%d status=%r", campaign_id, status
        )
