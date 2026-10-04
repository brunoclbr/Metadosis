"""The FastAPI application and its process-lifetime resources.

MongoDB checkpointing, Opik tracing, reusable outbound HTTP, and the LangGraph
workflow are enabled together here. The other client modules are alternatives,
not resources this application must initialize.
"""

from contextlib import asynccontextmanager
import logging
from typing import Any, AsyncIterator

import httpx
import uvicorn
from fastapi import FastAPI
from langgraph.checkpoint.mongodb import MongoDBSaver
from opik.integrations.langchain import OpikTracer, track_langgraph

from src.app.backend.api.routers import (
    brain,
    chat,
    system,
    visual_observations,
    webhooks,
)
from src.app.backend.services.brain_ingestion import BrainIngestionService
from src.app.backend.services.knowledge_graph import KnowledgeGraphService
from src.app.backend.services.teacher_context import TeacherContextService
from src.app.clients.elevenlabs import get_elevenlabs_client
from src.app.clients.model_providers import ModelProvider
from src.app.clients.mongodb import create_mongodb_client
from src.app.clients.neo4j import create_neo4j_client
from src.app.clients.postgres import create_postgres_client
from src.app.clients.vision import VisionObservationClient
from src.app.utils.opik_utils import configure as configure_opik
from src.config import settings

logger = logging.getLogger(__name__)


def _create_vision_observer() -> VisionObservationClient:
    """Create one reusable multimodal client without attaching trace callbacks."""
    model = ModelProvider(
        model_provider=settings.MODEL_PROVIDER,
        model_name=settings.MODEL_NAME,
    ).get_llm_client()
    return VisionObservationClient(
        model,
        provider_name=settings.MODEL_PROVIDER,
        model_name=settings.MODEL_NAME,
    )


def _compile_workflow(
    checkpointer: MongoDBSaver,
    http_client: httpx.AsyncClient,
) -> Any:
    """Bind this host's chosen clients and checkpointer to the graph definition."""
    # Keep these imports after Opik configuration: importing the graph imports prompts,
    # and prompt initialization may contact Opik for versioned prompt metadata.
    from src.agent.workflow.graph import create_workflow_graph
    from src.agent.workflow.tools import get_tools

    # The host injects infrastructure while graph.py receives only assembled tools.
    tools = get_tools(http_client)
    return create_workflow_graph(tools).compile(checkpointer=checkpointer)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Create shared infrastructure once per worker and clean it up at shutdown.

    Do not move this work back into ``/chat``: graph compilation, connection pools,
    checkpointers, and tracers are reusable infrastructure, while messages and
    thread IDs are request data. With multiple Uvicorn workers, each process runs
    its own lifespan and therefore owns its own copy of these Python objects.
    """
    configure_opik()
    mongo_client = create_mongodb_client()
    postgres_client = create_postgres_client()
    await postgres_client.initialize()
    elevenlabs_client = get_elevenlabs_client()
    vision_observer = _create_vision_observer()
    neo4j_client = create_neo4j_client()
    knowledge_graph = None
    if neo4j_client is not None:
        try:
            await neo4j_client.initialize()
            knowledge_graph = KnowledgeGraphService(postgres_client, neo4j_client)
        except Exception:
            logger.exception("knowledge_graph_unavailable reason=initialization_failed")
            await neo4j_client.close()
            neo4j_client = None
    brain_options: dict[str, Any] = {
        "settlement_delay_seconds": settings.BRAIN_EVIDENCE_SETTLEMENT_SECONDS,
    }
    if knowledge_graph is not None:
        brain_options["knowledge_graph"] = knowledge_graph
    brain = BrainIngestionService(
        postgres_client,
        ModelProvider(
            model_provider=settings.MODEL_PROVIDER,
            model_name=settings.MODEL_NAME,
        ).get_llm_client(),
        **brain_options,
    )
    # The read side needs no model: ElevenLabs owns the live pedagogical
    # reasoning and this service only assembles stored knowledge for it.
    teacher_context = (
        TeacherContextService(postgres_client, knowledge_graph)
        if knowledge_graph is not None
        else TeacherContextService(postgres_client)
    )
    http_client = httpx.AsyncClient(
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=20.0,
        follow_redirects=True,
    )
    tracer = None

    try:
        # Compilation attaches the selected persistence strategy. One compiled graph
        # can serve many conversation thread IDs; it is not compiled per user.
        # Lifespan runs once per worker: this graph is stored in app.state before
        # yield and reused by every request until shutdown, so @lru_cache is unnecessary.
        checkpointer = MongoDBSaver(mongo_client)
        workflow = _compile_workflow(checkpointer, http_client)
        tracer = OpikTracer(project_name=settings.COMET_PROJECT)
        tracked_workflow = track_langgraph(workflow, tracer)

        # app.state stores lifecycle-owned resources. Routes read them from the
        # current Request instead of importing hidden module-level singletons.
        # ElevenLabs belongs here rather than in graph state: the route can stream
        # provider chunks immediately without checkpointing a complete audio file.
        app.state.mongo_client = mongo_client
        app.state.postgres_client = postgres_client
        app.state.checkpointer = checkpointer
        app.state.workflow = tracked_workflow
        app.state.elevenlabs_client = elevenlabs_client
        app.state.vision_observer = vision_observer
        app.state.brain = brain
        app.state.knowledge_graph = knowledge_graph
        app.state.teacher_context = teacher_context
        app.state.tracer = tracer

        # FastAPI serves requests while execution is paused at this yield.
        yield
    finally:
        # Cleanup is nested so MongoDB and HTTP resources still close if flushing
        # observability data fails during shutdown.
        try:
            if tracer is not None:
                tracer.flush()
        finally:
            await http_client.aclose()
            if neo4j_client is not None:
                await neo4j_client.close()
            mongo_client.close()


app = FastAPI(title="LangGraph Backend API", lifespan=lifespan)
app.include_router(system.router)
app.include_router(chat.router)
app.include_router(visual_observations.router)
app.include_router(webhooks.router)
app.include_router(brain.router)


if __name__ == "__main__":
    uvicorn.run("src.app.backend.main:app", host="127.0.0.1", port=8000, reload=True)
