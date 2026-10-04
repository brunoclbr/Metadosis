"""Application orchestration for post-call Brain ingestion."""

import logging
from typing import Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.app.clients.postgres import PostgresClient
from src.domain.brain import (
    StructuredKnowledge,
    render_knowledge_markdown,
    screen_observations_as_text,
    transcript_as_text,
    validate_evidence_references,
)

logger = logging.getLogger(__name__)

DISTILLATION_PROMPT = """You distill expert training evidence into a work map.
Use only facts supported by the numbered transcript turns and screen observations.
Screen observations prove only what was visibly observed; do not infer intent or
reasons from them without transcript support. Never invent missing steps, reasons,
decisions, tools, artifacts, exceptions, or prohibitions. Give steps stable IDs
step_1, step_2, and so on. Every step must cite at least one supplied source using
its exact transcript turn number or screen observation event ID. Return the
requested structured object only."""


class BrainIngestionService:
    def __init__(self, postgres: PostgresClient, model: BaseChatModel) -> None:
        self.postgres = postgres
        self.structured_model = model.with_structured_output(
            StructuredKnowledge,
            method="json_schema",
        )

    async def accept_session(
        self,
        *,
        conversation_id: str,
        transcript: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> tuple[UUID, bool]:
        return await self.postgres.create_training_session(
            conversation_id=conversation_id,
            transcript=transcript,
            metadata=metadata,
        )

    async def distill_session(
        self,
        session_id: UUID,
        conversation_id: str,
        transcript: list[dict[str, Any]],
    ) -> None:
        """Distill one newly inserted session; callers can run this after responding."""
        await self.postgres.set_training_session_status(session_id, "processing")
        try:
            transcript_text = transcript_as_text(transcript)
            if not transcript_text:
                raise ValueError(
                    "The completed conversation contains no transcript text"
                )

            observations = await self.postgres.list_screen_observations(
                conversation_id
            )
            observations_text = screen_observations_as_text(observations)

            knowledge = await self.structured_model.ainvoke(
                [
                    SystemMessage(content=DISTILLATION_PROMPT),
                    HumanMessage(
                        content=(
                            f"Training transcript:\n\n{transcript_text}\n\n"
                            "Screen observations:\n\n"
                            f"{observations_text or 'None captured.'}"
                        )
                    ),
                ]
            )
            if not isinstance(knowledge, StructuredKnowledge):
                knowledge = StructuredKnowledge.model_validate(knowledge)
            validate_evidence_references(knowledge, transcript, observations)

            await self.postgres.create_knowledge_document(
                training_session_id=session_id,
                title=knowledge.title,
                structured_knowledge=knowledge.model_dump(mode="json"),
                markdown=render_knowledge_markdown(knowledge),
            )
            await self.postgres.set_training_session_status(session_id, "completed")
            logger.info(
                "brain_distillation_completed conversation_id=%s session_id=%s "
                "screen_observation_count=%s",
                conversation_id,
                session_id,
                len(observations),
            )
        except Exception:
            await self.postgres.set_training_session_status(session_id, "failed")
            logger.exception(
                "brain_distillation_failed conversation_id=%s session_id=%s",
                conversation_id,
                session_id,
            )
