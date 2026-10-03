"""Contracts for transient screen-frame observations."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ScreenFrameMetadata(BaseModel):
    """Browser-owned facts supplied in request headers."""

    session_id: UUID
    frame_id: int = Field(gt=0)
    captured_at: datetime
    width: int = Field(gt=0, le=8192)
    height: int = Field(gt=0, le=8192)
    thread_id: str | None = Field(default=None, min_length=1, max_length=256)


class ObservationModelMetadata(BaseModel):
    provider: str
    name: str


class ScreenObservationResponse(BaseModel):
    observation_id: UUID
    session_id: UUID
    frame_id: int
    captured_at: datetime
    description: str
    model: ObservationModelMetadata
