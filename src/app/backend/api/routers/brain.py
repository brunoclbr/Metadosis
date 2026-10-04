"""HTTP adapters for Processes and the knowledge one tutor session teaches from.

These routes stay thin: they validate input, call a lifecycle-owned service, and
validate the response. ``/teacher-context`` is called by the ElevenLabs tutor
branch over the public backend URL, not by the browser, so its payload is shaped
for a voice model rather than for a UI.
"""

import hmac
import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from src.app.backend.agent_schemas.brain import (
    ProcessCreateRequest,
    ProcessResponse,
)
from src.app.backend.services.teacher_context import (
    ProcessNotFoundError,
    ProcessNotTeachableError,
    ProvenanceIntegrityError,
)
from src.config import settings
from src.domain.brain import TeacherContext
from src.domain.knowledge_graph import ProcessGraph

router = APIRouter(prefix="/brain", tags=["brain"])
logger = logging.getLogger(__name__)

TOOL_SECRET_HEADER = "X-Metadosis-Tool-Secret"


def require_tool_secret(
    tool_secret: Annotated[str | None, Header(alias=TOOL_SECRET_HEADER)] = None,
) -> None:
    """Admit only the ElevenLabs tool to captured expertise.

    Enforcement follows the webhook's convention: the check is active exactly
    when a secret is configured. That keeps local development and an in-flight
    deployment working, because the backend and the agent configuration are
    published separately and whichever lands first must not break the other.
    An unconfigured secret is logged so the gap is visible rather than silent.
    """
    expected = settings.TEACHER_CONTEXT_SECRET
    if not expected:
        logger.warning("teacher_context_unauthenticated reason=no_secret_configured")
        return

    if not tool_secret or not hmac.compare_digest(tool_secret, expected):
        logger.warning(
            "teacher_context_rejected reason=%s",
            "missing_secret" if not tool_secret else "invalid_secret",
        )
        raise HTTPException(status_code=401, detail="Unauthorized.")


@router.get("/processes", response_model=list[ProcessResponse])
async def list_processes(request: Request) -> list[ProcessResponse]:
    """List every Process so Teach can reuse one and Learn can offer them."""
    rows = await request.app.state.postgres_client.list_processes()
    return [ProcessResponse.model_validate(row) for row in rows]


@router.post(
    "/processes",
    response_model=ProcessResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_process(
    payload: ProcessCreateRequest,
    request: Request,
) -> ProcessResponse:
    """Create a Process, resolving a repeated title to the existing one."""
    row, created = await request.app.state.postgres_client.create_process(
        title=payload.title,
        description=payload.description,
    )
    logger.info(
        "brain_process_upserted process_id=%s created=%s",
        row["id"],
        created,
    )
    return ProcessResponse.model_validate(row)


@router.get("/processes/{process_id}", response_model=ProcessResponse)
async def get_process(process_id: UUID, request: Request) -> ProcessResponse:
    row = await request.app.state.postgres_client.get_process(process_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Process not found.")
    return ProcessResponse.model_validate(row)


@router.get(
    "/processes/{process_id}/graph",
    response_model=ProcessGraph,
)
async def get_process_graph(
    process_id: UUID,
    request: Request,
) -> ProcessGraph:
    """Return only the requested Process-rooted graph for the Brain UI."""
    if await request.app.state.postgres_client.get_process(process_id) is None:
        raise HTTPException(status_code=404, detail="Process not found.")
    service = request.app.state.knowledge_graph
    if service is None:
        raise HTTPException(status_code=503, detail="Knowledge graph unavailable.")
    graph = await service.get_process_graph(process_id)
    if graph is None:
        raise HTTPException(
            status_code=409,
            detail="No validated knowledge has been projected for this process yet.",
        )
    return graph


@router.post(
    "/processes/{process_id}/graph/retry",
    dependencies=[Depends(require_tool_secret)],
)
async def retry_process_graph(
    process_id: UUID,
    request: Request,
) -> dict[str, int]:
    """Retry failed/pending projections without modifying authoritative Work Maps."""
    if await request.app.state.postgres_client.get_process(process_id) is None:
        raise HTTPException(status_code=404, detail="Process not found.")
    service = request.app.state.knowledge_graph
    if service is None:
        raise HTTPException(status_code=503, detail="Knowledge graph unavailable.")
    return await service.retry_process(process_id)


@router.get(
    "/processes/{process_id}/teacher-context",
    response_model=TeacherContext,
    dependencies=[Depends(require_tool_secret)],
)
async def get_teacher_context(
    process_id: UUID,
    request: Request,
) -> TeacherContext:
    """Return the current expert knowledge for one Process.

    A 409 means the Process is real but nothing has been taught into it yet. The
    tutor is expected to say so rather than improvise operational detail, so this
    distinction must survive as a status code and not collapse into a 404.
    """
    try:
        return await request.app.state.teacher_context.load(process_id)
    except ProcessNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Process not found.") from exc
    except ProvenanceIntegrityError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                "Captured expert knowledge failed provenance validation and "
                "cannot be taught safely."
            ),
        ) from exc
    except ProcessNotTeachableError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                "No completed expert training exists for this process yet. "
                "Tell the learner that the training has not established this "
                "material instead of answering from general knowledge."
            ),
        ) from exc
