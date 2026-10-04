"""Contracts for transient screen-frame comparisons and emitted events."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ScreenFramePairMetadata(BaseModel):
    """Browser-owned deterministic facts supplied in request headers."""

    session_id: UUID
    previous_frame_id: int = Field(gt=0)
    current_frame_id: int = Field(gt=0)
    occurred_at: datetime
    change_score: float = Field(ge=0, le=1)
    previous_width: int = Field(gt=0, le=8192)
    previous_height: int = Field(gt=0, le=8192)
    current_width: int = Field(gt=0, le=8192)
    current_height: int = Field(gt=0, le=8192)
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)


class ScreenEventResponse(BaseModel):
    event_id: UUID
    session_id: UUID
    previous_frame_id: int
    current_frame_id: int
    occurred_at: datetime
    change_score: float = Field(ge=0, le=1)
    summary: str = Field(min_length=1, max_length=4_000)


class PersistScreenEventRequest(ScreenEventResponse):
    conversation_id: str = Field(min_length=1, max_length=256)


class PersistScreenEventResponse(BaseModel):
    event_id: UUID
    status: str
