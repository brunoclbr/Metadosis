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
    transcript_as_text,
    validate_evidence_references,
    visual_observations_as_text,
)

logger = logging.getLogger(__name__)

DISTILLATION_PROMPT = """You distill expert training evidence into a work map.
Use only facts supported by the numbered transcript turns and visual observations.
Visual observations come from two inputs, each tagged with the evidence source you
must cite it under: screen_observation describes the expert's shared screen, and
camera_observation describes what the expert physically did in front of the camera.
Both prove only what was visibly observed; do not infer intent or reasons from them
without transcript support. A physical action is a step like any other: record what
was done and the expert's spoken reason for it, never a reason you supplied.
Never invent missing steps, reasons, decisions, tools, artifacts, exceptions, or
prohibitions. Give steps stable IDs step_1, step_2, and so on. Every step must cite
at least one supplied source using its exact transcript turn number, or an
observation's event ID under the exact source tag that observation was listed with.
Return the requested structured object only."""


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
        process_id: UUID | None = None,
    ) -> tuple[UUID, bool]:
        return await self.postgres.create_training_session(
            conversation_id=conversation_id,
            transcript=transcript,
            metadata=metadata,
            process_id=process_id,
        )

    async def skip_distillation(self, session_id: UUID) -> None:
        """Close a session that was recorded but is not expert training.

        A distinct terminal status keeps the record honest: ``received`` would
        imply distillation is still pending, and ``completed`` would imply a Work
        Map exists. The teacher-context read only accepts ``completed``, so a
        skipped session can never be served as expertise.
        """
        await self.postgres.set_training_session_status(session_id, "skipped")
        logger.info("brain_distillation_skipped session_id=%s", session_id)

    async def distill_session(
        self,
        session_id: UUID,
        conversation_id: str,
        transcript: list[dict[str, Any]],
        process_id: UUID | None = None,
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
            observations_text = visual_observations_as_text(observations)

            knowledge = await self.structured_model.ainvoke(
                [
                    SystemMessage(content=DISTILLATION_PROMPT),
                    HumanMessage(
                        content=(
                            f"Training transcript:\n\n{transcript_text}\n\n"
                            "Visual observations:\n\n"
                            f"{observations_text or 'None captured.'}"
                        )
                    ),
                ]
            )
            if not isinstance(knowledge, StructuredKnowledge):
                knowledge = StructuredKnowledge.model_validate(knowledge)
            validate_evidence_references(knowledge, transcript, observations)

            # The Process is recorded on the document as well as the session so
            # the teacher-context read never has to walk back through sessions.
            await self.postgres.create_knowledge_document(
                training_session_id=session_id,
                title=knowledge.title,
                structured_knowledge=knowledge.model_dump(mode="json"),
                markdown=render_knowledge_markdown(knowledge),
                process_id=process_id,
            )
            await self.postgres.set_training_session_status(session_id, "completed")
            logger.info(
                "brain_distillation_completed conversation_id=%s session_id=%s "
                "process_id=%s observation_count=%s camera_observation_count=%s",
                conversation_id,
                session_id,
                process_id,
                len(observations),
                sum(1 for item in observations if item.get("source") == "camera"),
            )
        except Exception:
            await self.postgres.set_training_session_status(session_id, "failed")
            logger.exception(
                "brain_distillation_failed conversation_id=%s session_id=%s",
                conversation_id,
                session_id,
            )
