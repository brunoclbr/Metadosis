"""Inbound webhook adapters."""

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request
from pydantic import ValidationError

from src.app.backend.agent_schemas.elevenlabs_webhook import (
    ElevenLabsPostCallPayload,
    PostCallAcceptedResponse,
)
from src.config import settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])
logger = logging.getLogger(__name__)


def _decode_and_verify(
    request: Request,
    raw_body: bytes,
    signature: str | None,
) -> dict[str, Any]:
    """Keep raw-body verification isolated so signing policy remains replaceable."""
    try:
        body = raw_body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Webhook body must be UTF-8 JSON."
        ) from exc

    if settings.ELEVENLABS_WEBHOOK_SECRET:
        try:
            return request.app.state.elevenlabs_client.webhooks.construct_event(
                rawBody=body,
                sig_header=signature or "",
                secret=settings.ELEVENLABS_WEBHOOK_SECRET,
            )
        except Exception as exc:
            logger.warning("elevenlabs_webhook_signature_rejected")
            raise HTTPException(
                status_code=401, detail="Invalid webhook signature."
            ) from exc

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400, detail="Webhook body must be valid JSON."
        ) from exc


@router.post(
    "/elevenlabs/post-call",
    response_model=PostCallAcceptedResponse,
)
async def elevenlabs_post_call(
    request: Request,
    background_tasks: BackgroundTasks,
    elevenlabs_signature: Annotated[
        str | None,
        Header(alias="ElevenLabs-Signature"),
    ] = None,
) -> PostCallAcceptedResponse:
    """Persist a completed conversation once, then distill it after responding."""
    raw_body = await request.body()
    logger.info(
        "elevenlabs_post_call_received content_length=%d signature_present=%s",
        len(raw_body),
        elevenlabs_signature is not None,
    )
    event = _decode_and_verify(request, raw_body, elevenlabs_signature)
    try:
        payload = ElevenLabsPostCallPayload.model_validate(event)
    except ValidationError as exc:
        logger.warning("elevenlabs_post_call_schema_rejected")
        raise HTTPException(
            status_code=422, detail="Invalid post-call payload."
        ) from exc

    if payload.type != "post_call_transcription":
        logger.warning(
            "elevenlabs_post_call_event_rejected event_type=%s",
            payload.type,
        )
        raise HTTPException(
            status_code=422, detail="Unsupported ElevenLabs event type."
        )

    conversation = payload.data
    provider_metadata = conversation.model_dump(
        mode="json",
        exclude={"conversation_id", "transcript", "messages", "metadata"},
        exclude_none=True,
    )
    metadata = {
        **conversation.metadata,
        **provider_metadata,
        "event_type": payload.type,
        "event_timestamp": payload.event_timestamp,
    }
    # The Process travels in the initiation dynamic variables the frontend set,
    # so it is known before distillation rather than reconstructed afterwards.
    process_id = conversation.process_id
    session_id, created = await request.app.state.brain.accept_session(
        conversation_id=conversation.conversation_id,
        transcript=conversation.transcript,
        metadata=metadata,
        process_id=process_id,
    )

    # Only an expert demonstration becomes a Work Map. A tutoring session is
    # recorded but never distilled: it would otherwise be stored as training for
    # the very Process it was teaching, and since the newest document wins, the
    # learner's own session would replace the expert's and the tutor would end up
    # teaching its own tool calls back to the next person.
    is_training = conversation.session_mode != "teaching"
    if created and is_training:
        background_tasks.add_task(
            request.app.state.brain.distill_session,
            session_id,
            conversation.conversation_id,
            conversation.transcript,
            process_id,
        )
    elif created:
        await request.app.state.brain.skip_distillation(session_id)

    logger.info(
        "elevenlabs_post_call_accepted conversation_id=%s session_id=%s "
        "process_id=%s session_mode=%s distilled=%s duplicate=%s "
        "transcript_messages=%d",
        conversation.conversation_id,
        session_id,
        process_id,
        conversation.session_mode,
        created and is_training,
        not created,
        len(conversation.transcript),
    )
    return PostCallAcceptedResponse(
        session_id=session_id,
        conversation_id=conversation.conversation_id,
        status="accepted" if created else "duplicate",
    )
