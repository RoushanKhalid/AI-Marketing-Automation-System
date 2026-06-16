"""
db/campaign_store.py — SQLite persistence layer for Campaign records.

CampaignStore wraps sqlite3 and provides all CRUD operations needed by
the API routes and the Scheduler. A threading.Lock ensures writes are
serialised when the background Scheduler thread and the API thread
access the database concurrently.

Schema includes generated_text and image_url columns so the web UI
can replay full message content after reconnecting.
"""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from typing import Optional

from app.logger import get_logger
from app.models.campaign import CampaignCreate, CampaignRecord

logger = get_logger(__name__)

_VALID_STATUSES = {"pending", "processing", "sent", "failed"}


class CampaignStore:
    """SQLite-backed repository for CampaignRecord objects."""

    def __init__(self, db_path: str = "campaigns.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()

        if db_path == ":memory:":
            self._conn: sqlite3.Connection | None = sqlite3.connect(
                ":memory:", check_same_thread=False
            )
            self._conn.row_factory = sqlite3.Row
        else:
            self._conn = None

        self._init_db()
        logger.info("CampaignStore initialised — database: %s", db_path)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_connection(self) -> tuple[sqlite3.Connection, bool]:
        if self._conn is not None:
            return self._conn, False
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn, True

    def _init_db(self) -> None:
        """Create the campaigns table (with all columns) if it does not exist,
        and add generated_text / image_url columns to existing databases."""
        ddl = """
        CREATE TABLE IF NOT EXISTS campaigns (
            campaign_id    INTEGER PRIMARY KEY AUTOINCREMENT,
            campaign_name  TEXT    NOT NULL,
            prompt         TEXT    NOT NULL,
            phone          TEXT    NOT NULL,
            schedule_time  TEXT    NOT NULL,
            status         TEXT    NOT NULL DEFAULT 'pending',
            generated_text TEXT,
            image_url      TEXT
        );
        """
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                conn.execute(ddl)
                # Migrate existing databases that lack the new columns
                existing_cols = {
                    row[1]
                    for row in conn.execute("PRAGMA table_info(campaigns)")
                }
                if "generated_text" not in existing_cols:
                    conn.execute("ALTER TABLE campaigns ADD COLUMN generated_text TEXT")
                    logger.info("Migrated DB: added generated_text column.")
                if "image_url" not in existing_cols:
                    conn.execute("ALTER TABLE campaigns ADD COLUMN image_url TEXT")
                    logger.info("Migrated DB: added image_url column.")
                conn.commit()
                logger.debug("campaigns table verified/created.")
            finally:
                if should_close:
                    conn.close()

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> CampaignRecord:
        keys = row.keys()
        return CampaignRecord(
            campaign_id=row["campaign_id"],
            campaign_name=row["campaign_name"],
            prompt=row["prompt"],
            phone=row["phone"],
            schedule_time=datetime.strptime(row["schedule_time"], "%Y-%m-%d %H:%M:%S"),
            status=row["status"],
            generated_text=row["generated_text"] if "generated_text" in keys else None,
            image_url=row["image_url"] if "image_url" in keys else None,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def _validate_campaign_record(self, campaign: CampaignCreate) -> None:
        """Validate a campaign record before database write operations.

        Raises:
            ValueError: If any required field is missing or format is invalid.
        """
        if not campaign.campaign_name or not campaign.campaign_name.strip():
            raise ValueError("campaign_name must be non-empty.")
        if len(campaign.campaign_name) > 255:
            raise ValueError("campaign_name must be max 255 characters.")

        if not campaign.prompt or not campaign.prompt.strip():
            raise ValueError("prompt must be non-empty.")
        if len(campaign.prompt) > 2000:
            raise ValueError("prompt must be max 2000 characters.")

        import re
        if not campaign.phone or not re.match(r"^\+[0-9]{7,15}$", campaign.phone):
            raise ValueError("phone must be in E.164 format (+ followed by 7-15 digits).")

        if not campaign.schedule_time:
            raise ValueError("schedule_time must be provided.")

        if campaign.status not in _VALID_STATUSES:
            raise ValueError(f"status must be one of: {sorted(_VALID_STATUSES)}")

    def create_campaign(self, campaign: CampaignCreate) -> CampaignRecord:
        """Insert a new campaign and return it with its assigned campaign_id."""
        self._validate_campaign_record(campaign)

        schedule_str = campaign.schedule_time.strftime("%Y-%m-%d %H:%M:%S")
        status = campaign.status or "pending"
        sql = """
        INSERT INTO campaigns (campaign_name, prompt, phone, schedule_time, status)
        VALUES (?, ?, ?, ?, ?)
        """
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                cursor = conn.execute(
                    sql,
                    (
                        campaign.campaign_name,
                        campaign.prompt,
                        campaign.phone,
                        schedule_str,
                        status,
                    ),
                )
                conn.commit()
                campaign_id = cursor.lastrowid
                logger.info(
                    "Campaign created — id=%d name=%r scheduled=%s status=%s",
                    campaign_id,
                    campaign.campaign_name,
                    schedule_str,
                    status,
                )
                return CampaignRecord(
                    campaign_id=campaign_id,
                    campaign_name=campaign.campaign_name,
                    prompt=campaign.prompt,
                    phone=campaign.phone,
                    schedule_time=campaign.schedule_time,
                    status=status,
                )
            except Exception as exc:
                conn.rollback()
                logger.error("Failed to create campaign: %s", exc)
                raise
            finally:
                if should_close:
                    conn.close()

    def get_campaign(self, campaign_id: int) -> Optional[CampaignRecord]:
        """Retrieve a single campaign by its ID."""
        sql = "SELECT * FROM campaigns WHERE campaign_id = ?"
        conn, should_close = self._get_connection()
        try:
            row = conn.execute(sql, (campaign_id,)).fetchone()
            if row is None:
                logger.debug("Campaign id=%d not found.", campaign_id)
                return None
            return self._row_to_record(row)
        finally:
            if should_close:
                conn.close()

    def list_campaigns(self) -> list[CampaignRecord]:
        """Return all campaigns ordered by schedule_time ascending."""
        sql = "SELECT * FROM campaigns ORDER BY schedule_time ASC"
        conn, should_close = self._get_connection()
        try:
            rows = conn.execute(sql).fetchall()
            logger.debug("list_campaigns — returned %d records.", len(rows))
            return [self._row_to_record(r) for r in rows]
        finally:
            if should_close:
                conn.close()

    def update_status(self, campaign_id: int, status: str) -> None:
        """Update the status of an existing campaign."""
        if status not in _VALID_STATUSES:
            raise ValueError(
                f"Invalid status {status!r}. Accepted values: {sorted(_VALID_STATUSES)}"
            )
        sql = "UPDATE campaigns SET status = ? WHERE campaign_id = ?"
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                cursor = conn.execute(sql, (status, campaign_id))
                conn.commit()
                if cursor.rowcount == 0:
                    raise LookupError(
                        f"Campaign with id={campaign_id} not found — status update aborted."
                    )
                logger.info("Campaign id=%d status updated to %r.", campaign_id, status)
            finally:
                if should_close:
                    conn.close()

    def update_dispatch_result(
        self,
        campaign_id: int,
        generated_text: str,
        image_url: str,
    ) -> None:
        """Persist generated text and image URL after successful dispatch."""
        sql = """
        UPDATE campaigns
           SET status = 'sent', generated_text = ?, image_url = ?
         WHERE campaign_id = ?
        """
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                cursor = conn.execute(sql, (generated_text, image_url, campaign_id))
                conn.commit()
                if cursor.rowcount == 0:
                    raise LookupError(
                        f"Campaign with id={campaign_id} not found — dispatch result update aborted."
                    )
                logger.info(
                    "Campaign id=%d dispatch result stored (text=%d chars).",
                    campaign_id,
                    len(generated_text),
                )
            finally:
                if should_close:
                    conn.close()

    def delete_campaign(self, campaign_id: int) -> bool:
        """Delete a campaign by ID. Returns True if deleted, False if not found."""
        sql = "DELETE FROM campaigns WHERE campaign_id = ?"
        with self._lock:
            conn, should_close = self._get_connection()
            try:
                cursor = conn.execute(sql, (campaign_id,))
                conn.commit()
                found = cursor.rowcount > 0
                if found:
                    logger.info("Campaign id=%d deleted.", campaign_id)
                else:
                    logger.warning("Delete: campaign id=%d not found.", campaign_id)
                return found
            finally:
                if should_close:
                    conn.close()

    def get_due_campaigns(self) -> list[CampaignRecord]:
        """Return pending campaigns whose scheduled time has arrived."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = """
        SELECT * FROM campaigns
        WHERE status = 'pending'
          AND schedule_time <= ?
        ORDER BY schedule_time ASC
        """
        conn, should_close = self._get_connection()
        try:
            rows = conn.execute(sql, (now_str,)).fetchall()
            if rows:
                logger.debug(
                    "get_due_campaigns — found %d due campaign(s) at %s.",
                    len(rows),
                    now_str,
                )
            return [self._row_to_record(r) for r in rows]
        finally:
            if should_close:
                conn.close()
