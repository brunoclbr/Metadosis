"""Validated boundary contracts for ElevenLabs post-call webhooks."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ElevenLabsConversationInitiationClientData(BaseModel):
    """The initiation data ElevenLabs echoes back on the post-call payload.

    ``dynamic_variables`` is how the browser's choice of Process survives the
    whole call: the frontend supplies it at ``startSession``, ElevenLabs carries
    it through the workflow, and it returns here unchanged. That makes it the
    authoritative record of what the expert was training, rather than something
    inferred after the fact.
    """

    model_config = ConfigDict(extra="allow")

    dynamic_variables: dict[str, Any] = Field(default_factory=dict)


class ElevenLabsConversationData(BaseModel):
    model_config = ConfigDict(extra="allow")

    conversation_id: str = Field(min_length=1, max_length=256)
    status: str | None = None
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    messages: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    conversation_initiation_client_data: (
        ElevenLabsConversationInitiationClientData | None
    ) = None

    @model_validator(mode="after")
    def normalize_transcript(self) -> "ElevenLabsConversationData":
        if not self.transcript and self.messages:
            self.transcript = self.messages
        return self

    @property
    def process_id(self) -> UUID | None:
        """Read the trained Process, tolerating calls started without one.

        A malformed or absent value yields ``None`` so an otherwise good training
        session is still stored and distilled; it simply is not attached to a
        Process and therefore is not teachable.
        """
        if self.conversation_initiation_client_data is None:
            return None

        raw = self.conversation_initiation_client_data.dynamic_variables.get(
            "process_id"
        )
        if not isinstance(raw, str) or not raw.strip():
            return None
        try:
            return UUID(raw.strip())
        except ValueError:
            return None


class ElevenLabsPostCallPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    type: str
    event_timestamp: int | None = None
    data: ElevenLabsConversationData


class PostCallAcceptedResponse(BaseModel):
    session_id: UUID
    conversation_id: str
    status: str
