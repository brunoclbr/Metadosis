"""Validated boundary contracts for ElevenLabs post-call webhooks."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ElevenLabsConversationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    conversation_id: str = Field(min_length=1, max_length=256)
    status: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_transcript(self) -> "ElevenLabsConversationData":
        if not self.transcript and self.messages:
            self.transcript = self.messages
        return self


class ElevenLabsPostCallPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    event_timestamp: int | None = None
    data: ElevenLabsConversationData


class PostCallAcceptedResponse(BaseModel):
    session_id: UUID
    conversation_id: str
    status: str
