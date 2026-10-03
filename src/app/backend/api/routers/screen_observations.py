"""HTTP ingestion seam for transient shared-screen frame comparisons."""

import asyncio
import io
import json
import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response, status
from PIL import Image, UnidentifiedImageError

from src.app.backend.agent_schemas.screen_observation import (
    ScreenEventResponse,
    ScreenFramePairMetadata,
)

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_PAIR_BYTES = 2 * MAX_IMAGE_BYTES
MAX_IMAGE_PIXELS = 16_000_000
ALLOWED_IMAGE_TYPES = {"image/jpeg": "JPEG"}
PAIR_CONTENT_TYPE = "application/octet-stream"
VLM_TIMEOUT_SECONDS = 60


def _log_event(event: str, **metadata: Any) -> None:
    """Emit searchable metadata without including screen-derived content."""
    logger.info("%s %s", event, json.dumps(metadata, default=str, sort_keys=True))


async def _read_bounded_body(request: Request, expected_bytes: int) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_bytes = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header.",
            ) from exc
        if declared_bytes > MAX_PAIR_BYTES:
            raise HTTPException(status_code=413, detail="Frame pair is too large.")
        if declared_bytes != expected_bytes:
            raise HTTPException(
                status_code=422,
                detail="Frame byte lengths do not match Content-Length.",
            )

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_PAIR_BYTES:
            raise HTTPException(status_code=413, detail="Frame pair is too large.")
    if len(body) != expected_bytes:
        raise HTTPException(
            status_code=422,
            detail="Frame byte lengths do not match the request body.",
        )
    return bytes(body)


def _validate_image(
    image_bytes: bytes,
    mime_type: str,
    expected_width: int,
    expected_height: int,
) -> tuple[int, int]:
    expected_format = ALLOWED_IMAGE_TYPES[mime_type]
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            if image.format != expected_format:
                raise HTTPException(
                    status_code=415,
                    detail="Image bytes do not match the supplied image type.",
                )
            if width * height > MAX_IMAGE_PIXELS:
                raise HTTPException(status_code=413, detail="Image dimensions are too large.")
            if (width, height) != (expected_width, expected_height):
                raise HTTPException(
                    status_code=422,
                    detail="Image dimensions do not match the supplied metadata.",
                )
            image.load()
    except HTTPException:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Image could not be decoded.") from exc
    return width, height


@router.post(
    "/screen-observations",
    response_model=ScreenEventResponse,
    responses={status.HTTP_204_NO_CONTENT: {"description": "Change suppressed"}},
    status_code=status.HTTP_200_OK,
)
async def create_screen_event(
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Screen-Session-Id")],
    previous_frame_id: Annotated[
        int,
        Header(alias="X-Screen-Previous-Frame-Id", gt=0),
    ],
    current_frame_id: Annotated[
        int,
        Header(alias="X-Screen-Current-Frame-Id", gt=0),
    ],
    occurred_at: Annotated[datetime, Header(alias="X-Screen-Occurred-At")],
    change_score: Annotated[
        float,
        Header(alias="X-Screen-Change-Score", ge=0, le=1),
    ],
    previous_width: Annotated[
        int,
        Header(alias="X-Screen-Previous-Width", gt=0, le=8192),
    ],
    previous_height: Annotated[
        int,
        Header(alias="X-Screen-Previous-Height", gt=0, le=8192),
    ],
    current_width: Annotated[
        int,
        Header(alias="X-Screen-Current-Width", gt=0, le=8192),
    ],
    current_height: Annotated[
        int,
        Header(alias="X-Screen-Current-Height", gt=0, le=8192),
    ],
    previous_bytes: Annotated[
        int,
        Header(alias="X-Screen-Previous-Bytes", gt=0),
    ],
    current_bytes: Annotated[
        int,
        Header(alias="X-Screen-Current-Bytes", gt=0),
    ],
    image_type: Annotated[str, Header(alias="X-Screen-Image-Type")],
    thread_id: Annotated[
        str | None,
        Header(alias="X-Thread-Id", min_length=1, max_length=256),
    ] = None,
) -> ScreenEventResponse | Response:
    """Compare two validated frames, emit an event if the change is meaningful."""
    started_at = time.perf_counter()
    request_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if request_type != PAIR_CONTENT_TYPE:
        raise HTTPException(status_code=415, detail="Invalid frame-pair content type.")
    if image_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG images are supported.")
    if previous_bytes > MAX_IMAGE_BYTES or current_bytes > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail="A screen frame is too large.")
    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Event timestamp must include UTC offset.")
    if previous_frame_id >= current_frame_id:
        raise HTTPException(
            status_code=422,
            detail="Current frame must follow previous frame.",
        )

    metadata = ScreenFramePairMetadata(
        session_id=session_id,
        previous_frame_id=previous_frame_id,
        current_frame_id=current_frame_id,
        occurred_at=occurred_at.astimezone(timezone.utc),
        change_score=change_score,
        previous_width=previous_width,
        previous_height=previous_height,
        current_width=current_width,
        current_height=current_height,
        thread_id=thread_id,
    )
    pair_bytes = await _read_bounded_body(request, previous_bytes + current_bytes)
    previous_image = pair_bytes[:previous_bytes]
    current_image = pair_bytes[previous_bytes:]
    _validate_image(
        previous_image,
        image_type,
        metadata.previous_width,
        metadata.previous_height,
    )
    _validate_image(
        current_image,
        image_type,
        metadata.current_width,
        metadata.current_height,
    )

    common_log_fields = {
        "session_id": metadata.session_id,
        "previous_frame_id": metadata.previous_frame_id,
        "current_frame_id": metadata.current_frame_id,
        "change_score": metadata.change_score,
        "previous_image_bytes": len(previous_image),
        "current_image_bytes": len(current_image),
        "previous_dimensions": [metadata.previous_width, metadata.previous_height],
        "current_dimensions": [metadata.current_width, metadata.current_height],
        "mime_type": image_type,
        "provider": request.app.state.vision_observer.provider_name,
        "model": request.app.state.vision_observer.model_name,
    }
    _log_event("screen_change_detected", **common_log_fields)
    _log_event("screen_event_vlm_started", **common_log_fields)

    vlm_started_at = time.perf_counter()
    try:
        async with asyncio.timeout(VLM_TIMEOUT_SECONDS):
            change = await request.app.state.vision_observer.compare(
                previous_image,
                current_image,
                image_type,
            )
    except TimeoutError as exc:
        _log_event(
            "screen_event_failed",
            **common_log_fields,
            total_latency_ms=round((time.perf_counter() - started_at) * 1000),
            status=504,
            error_code="vlm_timeout",
        )
        raise HTTPException(status_code=504, detail="Vision model timed out.") from exc
    except Exception as exc:
        _log_event(
            "screen_event_failed",
            **common_log_fields,
            total_latency_ms=round((time.perf_counter() - started_at) * 1000),
            status=502,
            error_code=type(exc).__name__,
        )
        logger.error(
            "Screen event VLM invocation failed session_id=%s error_type=%s",
            metadata.session_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Vision model request failed.") from exc

    vlm_latency_ms = round((time.perf_counter() - vlm_started_at) * 1000)
    total_latency_ms = round((time.perf_counter() - started_at) * 1000)
    _log_event(
        "screen_event_vlm_completed",
        **common_log_fields,
        meaningful_change=change.meaningful_change,
        summary_length=len(change.summary or ""),
        vlm_latency_ms=vlm_latency_ms,
        total_latency_ms=total_latency_ms,
        status=200,
    )
    if not change.meaningful_change:
        _log_event(
            "screen_event_suppressed",
            **common_log_fields,
            vlm_latency_ms=vlm_latency_ms,
            total_latency_ms=total_latency_ms,
            status=204,
        )
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    event_id = uuid4()
    event = ScreenEventResponse(
        event_id=event_id,
        session_id=metadata.session_id,
        previous_frame_id=metadata.previous_frame_id,
        current_frame_id=metadata.current_frame_id,
        occurred_at=metadata.occurred_at,
        summary=change.summary or "",
    )
    _log_event(
        "screen_event_emitted",
        **common_log_fields,
        event_id=event_id,
        vlm_latency_ms=vlm_latency_ms,
        total_latency_ms=total_latency_ms,
        status=200,
    )
    return event
