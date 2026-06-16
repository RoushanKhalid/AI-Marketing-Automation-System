"""
api/routes.py — FastAPI route handlers for campaign management.

Endpoints:
  POST   /campaigns                 — Create a new campaign
  GET    /campaigns                 — List all campaigns
  GET    /campaigns/sent            — Get all sent campaigns (UI replay on reconnect)
  GET    /campaigns/{campaign_id}   — Get a single campaign by ID
  DELETE /campaigns/{campaign_id}   — Delete a campaign (pending/failed only)
  GET    /health                    — Health check

IMPORTANT: Static path segments (/sent) must be declared BEFORE
parameterised segments (/{campaign_id}) to avoid FastAPI matching
"sent" as an integer campaign_id (which would return 422).
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, status

from app.logger import get_logger
from app.models.campaign import CampaignCreate, CampaignRecord

logger = get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

@router.get(
    "/health",
    summary="Health check",
    tags=["System"],
)
async def health_check() -> dict:
    """Return a simple alive signal."""
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Campaign endpoints — static routes FIRST, parameterised LAST
# ---------------------------------------------------------------------------

@router.get(
    "/campaigns/sent",
    response_model=list[CampaignRecord],
    summary="Get all sent campaigns with generated content (for UI replay on connect)",
    tags=["Campaigns"],
)
async def get_sent_campaigns(request: Request) -> list[CampaignRecord]:
    """Return all sent campaigns including generated_text and image_url.

    The web UI calls this on WebSocket connect to replay messages for
    campaigns that were dispatched before the browser was open.
    Results are ordered newest-first so the UI can show the latest first.
    """
    store = request.app.state.store
    all_campaigns = store.list_campaigns()
    sent = [c for c in all_campaigns if c.status == "sent"]
    sent_desc = list(reversed(sent))
    logger.debug("API: get_sent_campaigns — returned %d sent record(s).", len(sent_desc))
    return sent_desc


@router.post(
    "/campaigns",
    response_model=CampaignRecord,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new marketing campaign",
    tags=["Campaigns"],
)
async def create_campaign(payload: CampaignCreate, request: Request) -> CampaignRecord:
    """Create and persist a new campaign.

    The campaign will be picked up by the background Scheduler when its
    ``schedule_time`` is reached and its status is ``pending``.

    Returns:
        The newly created CampaignRecord with auto-assigned ``campaign_id``
        and default status ``pending``.

    Raises:
        HTTPException 422: Automatically raised by FastAPI on invalid input.
        HTTPException 500: On unexpected persistence errors.
    """
    store = request.app.state.store
    try:
        record = store.create_campaign(payload)
        logger.info(
            "API: campaign created — id=%d name=%r", record.campaign_id, record.campaign_name
        )
        return record
    except Exception as exc:
        logger.error("API: failed to create campaign — %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create campaign. Please try again.",
        ) from exc


@router.get(
    "/campaigns",
    response_model=list[CampaignRecord],
    summary="List all campaigns",
    tags=["Campaigns"],
)
async def list_campaigns(request: Request) -> list[CampaignRecord]:
    """Return all campaigns ordered by scheduled time (ascending)."""
    store = request.app.state.store
    campaigns = store.list_campaigns()
    logger.debug("API: list_campaigns — returned %d record(s).", len(campaigns))
    return campaigns


@router.get(
    "/campaigns/{campaign_id}",
    response_model=CampaignRecord,
    summary="Get a campaign by ID",
    tags=["Campaigns"],
)
async def get_campaign(campaign_id: int, request: Request) -> CampaignRecord:
    """Return a single campaign by its unique ID."""
    store = request.app.state.store
    record = store.get_campaign(campaign_id)
    if record is None:
        logger.warning("API: campaign id=%d not found.", campaign_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign with id {campaign_id} not found.",
        )
    logger.debug("API: get_campaign — id=%d found.", campaign_id)
    return record


@router.delete(
    "/campaigns/{campaign_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete a campaign",
    tags=["Campaigns"],
)
async def delete_campaign(campaign_id: int, request: Request) -> dict:
    """Delete a campaign by ID.

    Only campaigns with status ``pending`` or ``failed`` can be deleted.
    Attempting to delete a ``processing`` or ``sent`` campaign returns 409.

    Raises:
        HTTPException 404: Campaign not found.
        HTTPException 409: Campaign is processing or already sent.
        HTTPException 500: Unexpected persistence error.
    """
    store = request.app.state.store
    record = store.get_campaign(campaign_id)
    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Campaign with id {campaign_id} not found.",
        )
    if record.status in ("processing", "sent"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Campaign id {campaign_id} has status '{record.status}' "
                "and cannot be deleted. Only pending or failed campaigns can be deleted."
            ),
        )
    try:
        store.delete_campaign(campaign_id)
        logger.info("API: campaign id=%d deleted.", campaign_id)
        return {"deleted": campaign_id}
    except Exception as exc:
        logger.error("API: failed to delete campaign id=%d — %s", campaign_id, exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete campaign. Please try again.",
        ) from exc
