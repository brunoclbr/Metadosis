"""HTTP adapter for chat requests and responses."""

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.app.backend.agent_schemas.request_response import ChatRequest, ChatResponse
from src.config import settings

router = APIRouter()
logger = logging.getLogger(__name__)


def _latest_message_content(messages: list[Any]) -> str:
    """Normalize plain and provider-structured message content to text."""
    latest_message = messages[-1]
    content = getattr(latest_message, "content", "")
    if isinstance(content, str):
        return content

    text = getattr(latest_message, "text", None)
    if isinstance(text, str):
        return text

    raise TypeError(f"Unsupported message content type: {type(content).__name__}")


@router.post(
    "/chat",
    response_model=ChatResponse,
    responses={200: {"content": {"audio/mpeg": {}}}},
)
async def chat_endpoint(payload: ChatRequest, request: Request) -> Any:
    """Translate one HTTP chat request into a prepared graph invocation.

    Keep HTTP validation, invocation configuration, and response shaping here.
    Graph construction, persistence, and tracing belong to application lifespan;
    agent reasoning belongs under ``src/agent``.

    ``ainvoke`` keeps the request path asynchronous, but network-bound nodes must
    still await their own dependencies. Cheap routing and local tools may remain
    synchronous through LangGraph/LangChain's supported async execution path.

    The graph owns the durable answer text and delivery choice. For audio replies,
    this HTTP adapter passes ElevenLabs' async iterator directly to
    ``StreamingResponse`` instead of joining chunks in a graph node. That separation
    starts playback sooner, avoids buffering a complete file, and prevents binary
    transport data from entering checkpoint state. The graph still executes once.
    """
    try:
        # LangGraph's message reducer converts this compact tuple representation into
        # a HumanMessage. The caller's thread ID is invocation config, not graph state.
        initial_input = {"messages": [("user", payload.message)]}

        # Reusing a thread_id continues its checkpoint lineage; a new value starts
        # separate state. It is not a user ID or an authorization mechanism.
        # The recursion limit is a final guard against a model that keeps requesting
        # tools. Reaching it is treated as a failed run, not normal loop control.
        config = {
            "configurable": {"thread_id": str(payload.thread_id)},
            "recursion_limit": 25,
        }
        result = await request.app.state.workflow.ainvoke(
            initial_input,
            config=config,
        )
        answer = _latest_message_content(result["messages"])
        if result.get("response_type") == "audio":
            audio_chunks = request.app.state.elevenlabs_client.text_to_speech.convert(
                text=answer,
                voice_id=settings.ELEVENLABS_VOICE_ID,
                model_id=settings.ELEVENLABS_MODEL_ID,
                output_format="mp3_44100_128",
                optimize_streaming_latency=4,
            )
            return StreamingResponse(
                audio_chunks,
                media_type="audio/mpeg",
                headers={"Cache-Control": "no-store"},
            )

        return ChatResponse(response=answer)
    except Exception as exc:
        logger.exception("Chat endpoint failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc
