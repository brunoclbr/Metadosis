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
from typing import TYPE_CHECKING
from uuid import UUID

from src.app.clients.postgres import PostgresClient
from src.domain.brain import (
    StructuredKnowledge,
    TeacherContext,
    build_teacher_context,
)

if TYPE_CHECKING:
    from src.app.backend.services.knowledge_graph import KnowledgeGraphService

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
    def __init__(
        self,
        postgres: PostgresClient,
        knowledge_graph: "KnowledgeGraphService | None" = None,
    ) -> None:
        self.postgres = postgres
        self.knowledge_graph = knowledge_graph

    async def load(self, process_id: UUID) -> TeacherContext:
        process = await self.postgres.get_process(process_id)
        if process is None:
            raise ProcessNotFoundError(str(process_id))

        if self.knowledge_graph is None:
            current = await self.postgres.get_current_process_knowledge(process_id)
            documents = [current] if current is not None else []
        else:
            workflow = await self.knowledge_graph.get_workflow(process_id)
            if workflow is None or not workflow.knowledge_document_ids:
                documents = []
            else:
                documents = await self.postgres.get_process_knowledge_documents(
                    process_id,
                    knowledge_document_ids=workflow.knowledge_document_ids,
                )
                if len(documents) != len(set(workflow.knowledge_document_ids)):
                    raise ProvenanceIntegrityError(str(process_id))

        if not documents:
            logger.info(
                "teacher_context_unavailable process_id=%s reason=no_completed_document",
                process_id,
            )
            raise ProcessNotTeachableError(str(process_id))

        contexts = [
            await self._resolve_document(process_id, document)
            for document in documents
        ]
        if len(contexts) == 1:
            return contexts[0]

        evidence_by_id = {
            evidence.id: evidence
            for context in contexts
            for evidence in context.evidence
        }
        return TeacherContext(
            process_id=process_id,
            provenance_version=2,
            evidence_cutoff=max(
                (
                    context.evidence_cutoff
                    for context in contexts
                    if context.evidence_cutoff is not None
                ),
                default=None,
            ),
            title=str(process["title"]),
            objective=" | ".join(
                dict.fromkeys(context.objective for context in contexts)
            ),
            steps=[item for context in contexts for item in context.steps],
            decisions=[item for context in contexts for item in context.decisions],
            exceptions=[item for context in contexts for item in context.exceptions],
            never_do=[item for context in contexts for item in context.never_do],
            tools=list(dict.fromkeys(item for context in contexts for item in context.tools)),
            artifacts=list(
                dict.fromkeys(item for context in contexts for item in context.artifacts)
            ),
            gaps=[item for context in contexts for item in context.gaps],
            evidence=list(evidence_by_id.values()),
        )

    async def _resolve_document(
        self,
        process_id: UUID,
        document: dict,
    ) -> TeacherContext:
        try:
            knowledge = StructuredKnowledge.model_validate(
                document["structured_knowledge"]
            )
        except ValueError as exc:
            logger.warning(
                "teacher_context_rejected process_id=%s knowledge_document_id=%s "
                "reason=unsupported_evidence_shape",
                process_id,
                document["knowledge_document_id"],
            )
            raise ProvenanceIntegrityError(str(process_id)) from exc

        observations = await self.postgres.list_screen_observations(
            document["conversation_id"],
            created_before=document.get("evidence_cutoff"),
        )
        try:
            context = build_teacher_context(
                process_id=process_id,
                knowledge=knowledge,
                transcript=document["raw_transcript"],
                observations=observations,
                conversation_id=document["conversation_id"],
                metadata=document.get("metadata") or {},
                evidence_cutoff=document.get("evidence_cutoff"),
            )
        except ValueError as exc:
            logger.error(
                "teacher_context_rejected process_id=%s knowledge_document_id=%s "
                "reason=unresolved_or_invalid_provenance",
                process_id,
                document["knowledge_document_id"],
            )
            raise ProvenanceIntegrityError(str(process_id)) from exc
        logger.info(
            "teacher_context_document_resolved process_id=%s "
            "knowledge_document_id=%s step_count=%d evidence_count=%d",
            process_id,
            document["knowledge_document_id"],
            len(context.steps),
            len(context.evidence),
        )
        return context
