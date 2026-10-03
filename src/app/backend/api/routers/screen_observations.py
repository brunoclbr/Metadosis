"""HTTP ingestion boundary for transient shared-screen frames."""

import asyncio
import io
import json
import logging
import time
from datetime import datetime, timezone
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, status
from PIL import Image, UnidentifiedImageError

from src.app.backend.agent_schemas.screen_observation import (
    ObservationModelMetadata,
    ScreenFrameMetadata,
    ScreenObservationResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
ALLOWED_IMAGE_TYPES = {"image/jpeg": "JPEG"}
VLM_TIMEOUT_SECONDS = 60


def _log_event(event: str, **metadata: Any) -> None:
    """Emit searchable metadata without ever including screen-derived content."""
    logger.info("%s %s", event, json.dumps(metadata, default=str, sort_keys=True))


async def _read_bounded_body(request: Request) -> bytes:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_IMAGE_BYTES:
                raise HTTPException(status_code=413, detail="Image is too large.")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid Content-Length header.",
            ) from exc

    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_IMAGE_BYTES:
            raise HTTPException(status_code=413, detail="Image is too large.")
    if not body:
        raise HTTPException(status_code=400, detail="Image body is required.")
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
                    detail="Image bytes do not match Content-Type.",
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
    response_model=ScreenObservationResponse,
    status_code=status.HTTP_200_OK,
)
async def create_screen_observation(
    request: Request,
    session_id: Annotated[UUID, Header(alias="X-Screen-Session-Id")],
    frame_id: Annotated[int, Header(alias="X-Screen-Frame-Id", gt=0)],
    captured_at: Annotated[datetime, Header(alias="X-Screen-Captured-At")],
    width: Annotated[int, Header(alias="X-Screen-Width", gt=0, le=8192)],
    height: Annotated[int, Header(alias="X-Screen-Height", gt=0, le=8192)],
    thread_id: Annotated[
        str | None,
        Header(alias="X-Thread-Id", min_length=1, max_length=256),
    ] = None,
) -> ScreenObservationResponse:
    """Validate one frame, obtain a factual VLM description, then discard it."""
    started_at = time.perf_counter()
    observation_id = uuid4()
    mime_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
    if mime_type not in ALLOWED_IMAGE_TYPES:
        raise HTTPException(status_code=415, detail="Only JPEG images are supported.")
    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
        raise HTTPException(status_code=422, detail="Captured timestamp must include UTC offset.")

    metadata = ScreenFrameMetadata(
        session_id=session_id,
        frame_id=frame_id,
        captured_at=captured_at.astimezone(timezone.utc),
        width=width,
        height=height,
        thread_id=thread_id,
    )
    image_bytes = await _read_bounded_body(request)
    actual_width, actual_height = _validate_image(
        image_bytes,
        mime_type,
        metadata.width,
        metadata.height,
    )
    common_log_fields = {
        "session_id": metadata.session_id,
        "frame_id": metadata.frame_id,
        "observation_id": observation_id,
        "captured_at": metadata.captured_at.isoformat(),
        "received_at": datetime.now(timezone.utc).isoformat(),
        "mime_type": mime_type,
        "image_bytes": len(image_bytes),
        "width": actual_width,
        "height": actual_height,
        "provider": request.app.state.vision_observer.provider_name,
        "model": request.app.state.vision_observer.model_name,
    }
    _log_event("screen_frame_received", **common_log_fields)
    _log_event("screen_vlm_started", **common_log_fields)

    vlm_started_at = time.perf_counter()
    try:
        async with asyncio.timeout(VLM_TIMEOUT_SECONDS):
            description = await request.app.state.vision_observer.describe(
                image_bytes,
                mime_type,
            )
    except TimeoutError as exc:
        _log_event(
            "screen_vlm_failed",
            **common_log_fields,
            total_latency_ms=round((time.perf_counter() - started_at) * 1000),
            status=504,
            error_code="vlm_timeout",
        )
        raise HTTPException(status_code=504, detail="Vision model timed out.") from exc
    except Exception as exc:
        _log_event(
            "screen_vlm_failed",
            **common_log_fields,
            total_latency_ms=round((time.perf_counter() - started_at) * 1000),
            status=502,
            error_code=type(exc).__name__,
        )
        logger.error(
            "Screen VLM invocation failed observation_id=%s error_type=%s",
            observation_id,
            type(exc).__name__,
        )
        raise HTTPException(status_code=502, detail="Vision model request failed.") from exc

    _log_event(
        "screen_vlm_completed",
        **common_log_fields,
        vlm_latency_ms=round((time.perf_counter() - vlm_started_at) * 1000),
        total_latency_ms=round((time.perf_counter() - started_at) * 1000),
        description_length=len(description),
        status=200,
    )
    return ScreenObservationResponse(
        observation_id=observation_id,
        session_id=metadata.session_id,
        frame_id=metadata.frame_id,
        captured_at=metadata.captured_at,
        description=description,
        model=ObservationModelMetadata(
            provider=request.app.state.vision_observer.provider_name,
            name=request.app.state.vision_observer.model_name,
        ),
    )
