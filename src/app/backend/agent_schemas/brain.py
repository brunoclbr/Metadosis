"""Boundary contracts for Process selection and teacher context."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class ProcessCreateRequest(BaseModel):
    """One Process the expert is about to train or the learner wants to learn."""

    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)

    @field_validator("title", "description")
    @classmethod
    def strip_text(cls, value: str | None) -> str | None:
        """Normalize before the unique-title conflict check in PostgreSQL runs."""
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("title")
    @classmethod
    def require_title(cls, value: str | None) -> str:
        if not value:
            raise ValueError("A process title is required")
        return value


class ProcessResponse(BaseModel):
    id: UUID
    title: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime
