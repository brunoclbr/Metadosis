"""Read-side orchestration that serves captured expertise to the live tutor.

This is deliberately separate from ``brain_ingestion``: that service owns the
write path (accept a finished call, distill it, store it), while this one owns
the read path (resolve a Process, pick its current knowledge, render it for a
tutor). They share the PostgreSQL client and the Brain domain but have opposite
failure modes, so keeping them apart avoids a service that both writes training
data and answers live requests.

No LLM is involved here on purpose. ElevenLabs owns the pedagogical reasoning;
this layer only supplies structured knowledge.
"""

import logging
from uuid import UUID

from src.app.clients.postgres import PostgresClient
from src.domain.brain import (
    StructuredKnowledge,
    TeacherContext,
    build_teacher_context,
)

logger = logging.getLogger(__name__)


class ProcessNotFoundError(Exception):
    """The requested Process does not exist."""


class ProcessNotTeachableError(Exception):
    """The Process exists but has no knowledge a tutor could teach yet.

    Raised both when no expert has finished training the Process and when a
    stored document's citations cannot be parsed or resolved. Legacy turn-based
    citations remain supported; unavailable evidence is never invented.
    """


class ProvenanceIntegrityError(ProcessNotTeachableError):
    """Stored knowledge exists but its claimed source truth is invalid."""


class TeacherContextService:
    def __init__(self, postgres: PostgresClient) -> None:
        self.postgres = postgres

    async def load(self, process_id: UUID) -> TeacherContext:
        process = await self.postgres.get_process(process_id)
        if process is None:
            raise ProcessNotFoundError(str(process_id))

        current = await self.postgres.get_current_process_knowledge(process_id)
        if current is None:
            logger.info(
                "teacher_context_unavailable process_id=%s reason=no_completed_document",
                process_id,
            )
            raise ProcessNotTeachableError(str(process_id))

        try:
            knowledge = StructuredKnowledge.model_validate(
                current["structured_knowledge"]
            )
        except ValueError as exc:
            # Pre-provenance free-text evidence cannot be repaired without
            # inventing sources. Version-1 typed references remain supported.
            logger.warning(
                "teacher_context_rejected process_id=%s knowledge_document_id=%s "
                "reason=unsupported_evidence_shape",
                process_id,
                current["knowledge_document_id"],
            )
            raise ProvenanceIntegrityError(str(process_id)) from exc

        observations = await self.postgres.list_screen_observations(
            current["conversation_id"],
            created_before=current.get("evidence_cutoff"),
        )
        try:
            context = build_teacher_context(
                process_id=process_id,
                knowledge=knowledge,
                transcript=current["raw_transcript"],
                observations=observations,
                conversation_id=current["conversation_id"],
                metadata=current.get("metadata") or {},
                evidence_cutoff=current.get("evidence_cutoff"),
            )
        except ValueError as exc:
            logger.error(
                "teacher_context_rejected process_id=%s knowledge_document_id=%s "
                "reason=unresolved_or_invalid_provenance",
                process_id,
                current["knowledge_document_id"],
            )
            raise ProvenanceIntegrityError(str(process_id)) from exc
        logger.info(
            "teacher_context_served process_id=%s knowledge_document_id=%s "
            "step_count=%d evidence_count=%d",
            process_id,
            current["knowledge_document_id"],
            len(context.steps),
            len(context.evidence),
        )
        return context
