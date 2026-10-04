"""Contracts for transient visual-frame comparisons and emitted events."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from src.app.clients.vision import VisualSource


class VisualFramePairMetadata(BaseModel):
    """Browser-owned deterministic facts supplied in request headers."""

    session_id: UUID
    # Which visual input produced the pair. Screen is the default so a browser
    # built before cameras existed still describes itself correctly.
    source: VisualSource = "screen"
    previous_frame_id: int = Field(gt=0)
    current_frame_id: int = Field(gt=0)
    occurred_at: datetime
    change_score: float = Field(ge=0, le=1)
    previous_width: int = Field(gt=0, le=8192)
    previous_height: int = Field(gt=0, le=8192)
    current_width: int = Field(gt=0, le=8192)
    current_height: int = Field(gt=0, le=8192)
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)


class VisualEventResponse(BaseModel):
    event_id: UUID
    session_id: UUID
    source: VisualSource = "screen"
    previous_frame_id: int
    current_frame_id: int
    occurred_at: datetime
    change_score: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=4_000)


class PersistVisualEventRequest(VisualEventResponse):
    conversation_id: str = Field(min_length=1, max_length=256)


class PersistVisualEventResponse(BaseModel):
    event_id: UUID
    status: str
