"""
models/campaign.py — Pydantic models for Campaign data.

CampaignCreate  — validated input model (used by the API for POST /campaigns).
CampaignRecord  — full record model including campaign_id, status, and
                  generated_text / image_url (stored after dispatch so the
                  UI can replay messages after reconnect).

schedule_time is stored and returned as "YYYY-MM-DD HH:MM:SS" strings
throughout the system so the JS UI can display them directly.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal, Optional, Any

from pydantic import BaseModel, Field, field_validator, field_serializer


class CampaignCreate(BaseModel):
    """Input model for creating a new campaign."""

    campaign_name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable name for the campaign.",
    )
    prompt: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="Natural-language marketing prompt sent to the AI.",
    )
    phone: str = Field(
        ...,
        pattern=r"^\+[0-9]{7,15}$",
        description="Target phone number in E.164 format (e.g. +8801913828774).",
    )
    schedule_time: datetime = Field(
        ...,
        description="UTC datetime when the campaign should be dispatched.",
    )
    status: Literal["pending", "processing", "sent", "failed"] = Field(
        default="pending",
        description="Current lifecycle state of the campaign.",
    )

    @field_validator("campaign_name", "prompt", mode="before")
    @classmethod
    def strip_and_reject_blank(cls, value: str, info) -> str:
        stripped = value.strip() if isinstance(value, str) else value
        if not stripped:
            raise ValueError(f"{info.field_name} must not be blank.")
        return stripped

    @field_validator("schedule_time", mode="before")
    @classmethod
    def validate_schedule_time_format(cls, value: Any) -> datetime:
        """Enforce strict YYYY-MM-DD HH:MM:SS format validation for input string."""
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            try:
                return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            except ValueError as exc:
                raise ValueError(
                    "schedule_time must be in the format 'YYYY-MM-DD HH:MM:SS'."
                ) from exc
        raise ValueError("schedule_time must be a string or a datetime object.")

    @field_validator("status", mode="before")
    @classmethod
    def validate_status(cls, value: Any) -> str:
        """Validate status at creation and provide allowed values list if invalid."""
        if value is None:
            return "pending"
        valid_statuses = {"pending", "processing", "sent", "failed"}
        if value not in valid_statuses:
            raise ValueError(
                f"Invalid status '{value}'. Accepted values: {sorted(list(valid_statuses))}."
            )
        return value

    @field_serializer("schedule_time")
    def serialize_schedule_time(self, v: datetime) -> str:
        """Always serialize schedule_time as 'YYYY-MM-DD HH:MM:SS' string."""
        return v.strftime("%Y-%m-%d %H:%M:%S")


class CampaignRecord(CampaignCreate):
    """Full campaign record returned by the API and used internally."""

    campaign_id: int = Field(..., description="Auto-assigned unique identifier.")
    # Populated after successful dispatch so the UI can replay messages
    generated_text: Optional[str] = Field(
        default=None,
        description="AI-generated marketing copy (set after dispatch).",
    )
    image_url: Optional[str] = Field(
        default=None,
        description="Pollinations.AI image URL (set after dispatch).",
    )

    model_config = {
        "from_attributes": True,
    }
