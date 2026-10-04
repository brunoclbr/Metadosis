"""Application orchestration for post-call Brain ingestion."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from src.app.clients.postgres import PostgresClient
from src.domain.brain import (
    StructuredKnowledge,
    is_teachable,
    render_knowledge_markdown,
    salvage_unbacked_claims,
    transcript_as_text,
    validate_evidence_references,
    visual_observations_as_text,
)

logger = logging.getLogger(__name__)

# One repair attempt, then salvage. A rejected work map is usually under-cited
# rather than unsupported: the distiller stops citing the expert turn it already
# used for earlier steps, and naming the violation is enough for it to fix its
# own citations. Looping further would spend tokens re-deciding the same call.
MAX_DISTILLATION_ATTEMPTS = 2

REPAIR_INSTRUCTION = """Your previous work map was rejected by provenance
validation with this error:

{errors}

Return the work map again, corrected. Every non-empty why, every decision, every
exception and every never_do guardrail must cite at least one supplied
transcript turn spoken by the expert (role user), with that turn's exact
source_id and turn number. A single expert turn may support several steps when
it genuinely explains them.

Do not invent a citation, and do not move a source onto a claim it does not
support. If the expert never explained a step, send that step with why set to an
empty string rather than citing an unrelated turn. Dropping an unsupported
reason is correct; fabricating a source is not."""

DISTILLATION_PROMPT = """You distill expert training evidence into a work map.
Set provenance_version to 2. Use only facts supported by the supplied transcript
turns and visual observations. Cite transcript turns with both their exact source_id
and turn number. Cite observations with their exact event ID and source tag.
Visual observations come from two inputs: screen_observation describes the expert's
shared screen, and camera_observation describes what the expert physically did.
They prove only what was visibly observed; they never prove intent or reasoning.
Every step must cite at least one supplied source. Every non-empty why, every
decision, every exception, and every never_do guardrail must cite at least one user
(expert) transcript turn. Represent exceptions and never_do entries as objects with
statement and evidence. Visual evidence may additionally support an observed action.
Never infer causality merely because two sources are close in time. Never invent
missing steps, reasons, decisions, tools, artifacts, exceptions, or prohibitions.
Give steps stable IDs step_1, step_2, and so on. Return the requested structured
object only."""


class BrainIngestionService:
    def __init__(
        self,
        postgres: PostgresClient,
        model: BaseChatModel,
        *,
        settlement_delay_seconds: float = 0,
    ) -> None:
        self.postgres = postgres
        self.settlement_delay_seconds = max(0, settlement_delay_seconds)
        # include_raw keeps the model's JSON reachable when it fails our stronger
        # v2 contract. Without it the parser raises and the output is lost, which
        # leaves nothing to quote back for repair and nothing to salvage.
        self.structured_model = model.with_structured_output(
            StructuredKnowledge,
            method="json_schema",
            include_raw=True,
        )

    async def resolve_training_process(self, process_id: UUID | None) -> UUID | None:
        """Drop a Process this Brain has never heard of, keeping the session.

        The post-call webhook always targets the deployed backend, so a session
        started against a locally running frontend arrives carrying a process_id
        that exists only in the local database. Inserting it violates the
        foreign key and the entire session is lost to a 500 — transcript and
        all. Recording it without a Process preserves the evidence and leaves it
        unteachable, which is precisely what an unknown Process means here.
        """
        if process_id is None:
            return None
        if await self.postgres.get_process(process_id) is None:
            logger.warning(
                "brain_process_unknown process_id=%s reason=not_in_this_database",
                process_id,
            )
            return None
        return process_id

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
        metadata: dict[str, Any],
        process_id: UUID | None = None,
    ) -> None:
        """Distill one newly inserted session after its evidence settlement window."""
        await self.postgres.set_training_session_status(session_id, "processing")
        try:
            transcript_text = transcript_as_text(
                transcript,
                conversation_id=conversation_id,
                metadata=metadata,
            )
            if not transcript_text:
                raise ValueError(
                    "The completed conversation contains no transcript text"
                )

            # This small replaceable settlement seam lets browser VLM/persistence
            # requests already in flight finish before the one final source query.
            if self.settlement_delay_seconds:
                await asyncio.sleep(self.settlement_delay_seconds)
            evidence_cutoff = datetime.now(timezone.utc)
            observations = await self.postgres.list_screen_observations(
                conversation_id,
                created_before=evidence_cutoff,
            )
            observations_text = visual_observations_as_text(observations)

            knowledge, gaps = await self._distill_work_map(
                transcript_text=transcript_text,
                observations_text=observations_text,
                transcript=transcript,
                observations=observations,
                conversation_id=conversation_id,
            )

            # A session that produced no step, decision or prohibition taught
            # nothing. Storing it as completed would make it the newest document
            # for the Process and silently hide every real session before it.
            if not is_teachable(knowledge):
                logger.warning(
                    "brain_distillation_not_teachable conversation_id=%s "
                    "session_id=%s gap_count=%d",
                    conversation_id,
                    session_id,
                    len(gaps),
                )
                await self.skip_distillation(session_id)
                return

            # The Process is recorded on the document as well as the session so
            # the teacher-context read never has to walk back through sessions.
            await self.postgres.create_knowledge_document(
                training_session_id=session_id,
                title=knowledge.title,
                structured_knowledge=knowledge.model_dump(mode="json"),
                markdown=render_knowledge_markdown(knowledge),
                process_id=process_id,
                evidence_cutoff=evidence_cutoff,
                provenance_version=knowledge.provenance_version,
            )
            await self.postgres.set_training_session_status(session_id, "completed")
            logger.info(
                "brain_distillation_completed conversation_id=%s session_id=%s "
                "process_id=%s observation_count=%s camera_observation_count=%s "
                "step_count=%d gap_count=%d",
                conversation_id,
                session_id,
                process_id,
                len(observations),
                sum(1 for item in observations if item.get("source") == "camera"),
                len(knowledge.steps),
                len(gaps),
            )
        except Exception:
            await self.postgres.set_training_session_status(session_id, "failed")
            logger.exception(
                "brain_distillation_failed conversation_id=%s session_id=%s",
                conversation_id,
                session_id,
            )

    async def _distill_work_map(
        self,
        *,
        transcript_text: str,
        observations_text: str,
        transcript: list[dict[str, Any]],
        observations: list[dict[str, Any]],
        conversation_id: str,
    ) -> tuple[StructuredKnowledge, list[str]]:
        """Distil one session, repairing citations once before salvaging.

        Provenance stays fail-closed in what it accepts: the returned work map
        always passes the full v2 contract. What changed is the consequence of
        failure. A single uncited step used to discard an entire session, so a
        quiet demonstration could destroy the knowledge it did capture.
        """
        sources = HumanMessage(
            content=(
                f"Training transcript:\n\n{transcript_text}\n\n"
                "Visual observations:\n\n"
                f"{observations_text or 'None captured.'}"
            )
        )
        rejection: str | None = None
        data: dict[str, Any] = {}

        for attempt in range(1, MAX_DISTILLATION_ATTEMPTS + 1):
            messages: list[Any] = [
                SystemMessage(content=DISTILLATION_PROMPT),
                sources,
            ]
            if rejection is not None:
                messages.append(
                    HumanMessage(
                        content=REPAIR_INSTRUCTION.format(errors=rejection)
                    )
                )

            data = _distilled_payload(await self.structured_model.ainvoke(messages))
            # The compatibility model defaults a missing version to v1. A fresh
            # distillation is always judged under the stronger v2 contract.
            data["provenance_version"] = 2
            try:
                knowledge = StructuredKnowledge.model_validate(data)
                validate_evidence_references(
                    knowledge,
                    transcript,
                    observations,
                    conversation_id=conversation_id,
                )
                return knowledge, []
            except ValueError as exc:
                rejection = str(exc)
                logger.warning(
                    "brain_distillation_rejected conversation_id=%s attempt=%d/%d "
                    "reason=%s",
                    conversation_id,
                    attempt,
                    MAX_DISTILLATION_ATTEMPTS,
                    rejection,
                )

        salvaged, gaps = salvage_unbacked_claims(
            data,
            transcript,
            observations,
            conversation_id=conversation_id,
        )
        salvaged["provenance_version"] = 2
        knowledge = StructuredKnowledge.model_validate(salvaged)
        validate_evidence_references(
            knowledge,
            transcript,
            observations,
            conversation_id=conversation_id,
        )
        logger.warning(
            "brain_distillation_salvaged conversation_id=%s gap_count=%d gaps=%s",
            conversation_id,
            len(gaps),
            "; ".join(gaps),
        )
        return knowledge, gaps


def _distilled_payload(result: Any) -> dict[str, Any]:
    """Recover the distiller's JSON whether or not it satisfied the contract."""
    if isinstance(result, StructuredKnowledge):
        return result.model_dump(mode="json")
    if not isinstance(result, dict):
        raise ValueError("The distiller returned an unexpected result shape")

    parsed = result.get("parsed")
    if isinstance(parsed, StructuredKnowledge):
        return parsed.model_dump(mode="json")
    if isinstance(parsed, dict):
        return dict(parsed)

    raw = result.get("raw")
    for call in getattr(raw, "tool_calls", None) or []:
        arguments = call.get("args") if isinstance(call, dict) else None
        if isinstance(arguments, dict):
            return dict(arguments)
    content = getattr(raw, "content", None)
    if isinstance(content, str) and content.strip():
        try:
            decoded = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError("The distiller returned unparsable JSON") from exc
        if isinstance(decoded, dict):
            return decoded
    raise ValueError("The distiller returned no work map")
