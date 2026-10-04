import asyncio
import io
import logging
from types import SimpleNamespace
from typing import Annotated, Any, TypedDict

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from PIL import Image

from src.app.backend import main
from src.app.backend.api.routers import visual_observations
from src.app.clients.vision import VisualChange


class FakeMongoClient:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakePostgresClient:
    def __init__(self) -> None:
        self.initialized = False
        self.screen_observations: list[dict[str, Any]] = []

    async def initialize(self) -> None:
        self.initialized = True

    async def create_screen_observation(self, **observation: Any) -> bool:
        existing = next(
            (
                item
                for item in self.screen_observations
                if item["event_id"] == observation["event_id"]
            ),
            None,
        )
        if existing:
            if existing["conversation_id"] != observation["conversation_id"]:
                raise ValueError("Screen event is already bound")
            return False
        self.screen_observations.append(observation)
        return True


class FakeBrain:
    def __init__(
        self,
        postgres: Any,
        model: Any,
        *,
        settlement_delay_seconds: float = 0,
    ) -> None:
        self.postgres = postgres
        self.model = model
        self.settlement_delay_seconds = settlement_delay_seconds


class FakeElevenLabsClient:
    class TextToSpeech:
        def __init__(self) -> None:
            self.requests: list[dict[str, Any]] = []

        def convert(self, **kwargs: Any):
            self.requests.append(kwargs)

            async def chunks():
                yield b"audio-"
                await asyncio.sleep(0)
                yield b"bytes"

            return chunks()

    def __init__(self) -> None:
        self.text_to_speech = self.TextToSpeech()


class FakeVisionObserver:
    provider_name = "test-provider"
    model_name = "test-vision-model"

    def __init__(self) -> None:
        self.requests: list[tuple[bytes, bytes, str, str]] = []
        self.error: Exception | None = None
        self.delay = 0.0
        self.change = VisualChange(
            meaningful_change=True,
            summary="The visible form value changed.",
        )

    async def compare(
        self,
        previous_image: bytes,
        current_image: bytes,
        mime_type: str,
        source: str = "screen",
    ) -> VisualChange:
        self.requests.append((previous_image, current_image, mime_type, source))
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.change


class FakeTracer:
    def __init__(self, project_name: str | None = None) -> None:
        self.project_name = project_name
        self.flushed = False

    def flush(self) -> None:
        self.flushed = True


class FakeWorkflow:
    def __init__(self) -> None:
        self.messages_by_thread: dict[str, list[str]] = {}
        self.invocations: list[tuple[str, int, int]] = []

    async def ainvoke(
        self,
        message: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        thread_id = config["configurable"]["thread_id"]
        user_message = message["messages"][0][1]
        history = self.messages_by_thread.setdefault(thread_id, [])
        history.append(user_message)
        self.invocations.append((thread_id, id(self), config["recursion_limit"]))
        return {
            "messages": [SimpleNamespace(content=f"{thread_id}:{len(history)}")],
            "response_type": "audio" if "audio" in user_message else "text",
        }


def _install_lifecycle_fakes(monkeypatch):
    mongo_client = FakeMongoClient()
    postgres_client = FakePostgresClient()
    elevenlabs_client = FakeElevenLabsClient()
    workflow = FakeWorkflow()
    vision_observer = FakeVisionObserver()
    created: dict[str, Any] = {
        "configure_calls": 0,
        "saver_calls": 0,
        "compile_calls": 0,
        "track_calls": 0,
    }

    def configure_opik() -> None:
        created["configure_calls"] += 1

    def create_mongodb_client() -> FakeMongoClient:
        return mongo_client

    def create_saver(client: FakeMongoClient) -> SimpleNamespace:
        created["saver_calls"] += 1
        return SimpleNamespace(client=client)

    def compile_workflow(
        checkpointer: SimpleNamespace,
        http_client: Any,
    ) -> FakeWorkflow:
        created["compile_calls"] += 1
        created["checkpointer"] = checkpointer
        created["http_client"] = http_client
        return workflow

    def create_tracer(project_name: str | None = None) -> FakeTracer:
        tracer = FakeTracer(project_name)
        created["tracer"] = tracer
        return tracer

    def track_workflow(candidate: FakeWorkflow, tracer: FakeTracer) -> FakeWorkflow:
        created["track_calls"] += 1
        created["tracked_tracer"] = tracer
        return candidate

    monkeypatch.setattr(main, "configure_opik", configure_opik)
    monkeypatch.setattr(main, "create_mongodb_client", create_mongodb_client)
    monkeypatch.setattr(main, "create_postgres_client", lambda: postgres_client)
    monkeypatch.setattr(main, "create_neo4j_client", lambda: None)
    monkeypatch.setattr(main, "BrainIngestionService", FakeBrain)
    monkeypatch.setattr(main, "get_elevenlabs_client", lambda: elevenlabs_client)
    monkeypatch.setattr(main, "_create_vision_observer", lambda: vision_observer)
    monkeypatch.setattr(main, "MongoDBSaver", create_saver)
    monkeypatch.setattr(main, "_compile_workflow", compile_workflow)
    monkeypatch.setattr(main, "OpikTracer", create_tracer)
    monkeypatch.setattr(main, "track_langgraph", track_workflow)

    created["elevenlabs_client"] = elevenlabs_client
    created["postgres_client"] = postgres_client
    created["vision_observer"] = vision_observer
    return mongo_client, workflow, created


def test_lifespan_initializes_once_and_cleans_up(monkeypatch) -> None:
    mongo_client, workflow, created = _install_lifecycle_fakes(monkeypatch)

    with TestClient(main.app) as client:
        assert client.app.state.workflow is workflow
        assert client.app.state.elevenlabs_client is created["elevenlabs_client"]
        assert client.app.state.postgres_client is created["postgres_client"]
        assert client.app.state.postgres_client.initialized
        assert client.app.state.vision_observer is created["vision_observer"]
        assert created["configure_calls"] == 1
        assert created["saver_calls"] == 1
        assert created["compile_calls"] == 1
        assert created["track_calls"] == 1
        assert created["checkpointer"].client is mongo_client
        assert created["tracked_tracer"] is created["tracer"]
        assert not created["tracer"].flushed
        assert not created["http_client"].is_closed
        assert not mongo_client.closed

    assert created["tracer"].flushed
    assert created["http_client"].is_closed
    assert mongo_client.closed


def test_audio_response_streams_provider_chunks_without_checkpointing_bytes(
    monkeypatch,
) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)

    with TestClient(main.app) as client:
        response = client.post(
            "/chat",
            json={"message": "reply with audio", "thread_id": "audio-thread"},
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/mpeg")
    assert response.content == b"audio-bytes"
    assert created["elevenlabs_client"].text_to_speech.requests == [
        {
            "text": "audio-thread:1",
            "voice_id": main.settings.ELEVENLABS_VOICE_ID,
            "model_id": main.settings.ELEVENLABS_MODEL_ID,
            "output_format": "mp3_44100_128",
            "optimize_streaming_latency": 4,
        }
    ]


def test_requests_share_workflow_and_preserve_thread_state(monkeypatch) -> None:
    _, workflow, created = _install_lifecycle_fakes(monkeypatch)

    with TestClient(main.app) as client:
        first_a = client.post("/chat", json={"message": "one", "thread_id": "A"})
        first_b = client.post("/chat", json={"message": "other", "thread_id": "B"})
        second_a = client.post("/chat", json={"message": "two", "thread_id": "A"})

        assert first_a.json() == {"response": "A:1"}
        assert first_b.json() == {"response": "B:1"}
        assert second_a.json() == {"response": "A:2"}
        assert all(
            workflow_id == id(workflow) and recursion_limit == 25
            for _, workflow_id, recursion_limit in workflow.invocations
        )
        assert created["compile_calls"] == 1
        assert created["track_calls"] == 1


class ConversationState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def test_compiled_graph_separates_threads_and_continues_same_thread() -> None:
    def count_user_messages(state: ConversationState) -> dict[str, list[AIMessage]]:
        count = sum(isinstance(message, HumanMessage) for message in state["messages"])
        return {"messages": [AIMessage(content=str(count))]}

    builder = StateGraph(ConversationState)
    builder.add_node("respond", count_user_messages)
    builder.add_edge(START, "respond")
    builder.add_edge("respond", END)
    workflow = builder.compile(checkpointer=InMemorySaver())

    async def invoke_threads() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        first_a = await workflow.ainvoke(
            {"messages": [("user", "one")]},
            config={"configurable": {"thread_id": "A"}},
        )
        first_b = await workflow.ainvoke(
            {"messages": [("user", "other")]},
            config={"configurable": {"thread_id": "B"}},
        )
        second_a = await workflow.ainvoke(
            {"messages": [("user", "two")]},
            config={"configurable": {"thread_id": "A"}},
        )
        return first_a, first_b, second_a

    first_a, first_b, second_a = asyncio.run(invoke_threads())

    assert first_a["messages"][-1].content == "1"
    assert first_b["messages"][-1].content == "1"
    assert second_a["messages"][-1].content == "2"


def _jpeg_bytes(width: int = 16, height: int = 12) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), color="white").save(output, format="JPEG")
    return output.getvalue()


def _screen_pair_headers(
    previous: bytes,
    current: bytes,
    **overrides: str,
) -> dict[str, str]:
    headers = {
        "Content-Type": "application/octet-stream",
        "X-Screen-Image-Type": "image/jpeg",
        "X-Screen-Session-Id": "12345678-1234-4234-8234-123456789abc",
        "X-Screen-Previous-Frame-Id": "11",
        "X-Screen-Current-Frame-Id": "12",
        "X-Screen-Occurred-At": "2026-01-02T03:04:05Z",
        "X-Screen-Change-Score": "0.125",
        "X-Screen-Previous-Width": "16",
        "X-Screen-Previous-Height": "12",
        "X-Screen-Current-Width": "16",
        "X-Screen-Current-Height": "12",
        "X-Screen-Previous-Bytes": str(len(previous)),
        "X-Screen-Current-Bytes": str(len(current)),
        "X-Thread-Id": "web-test",
    }
    headers.update(overrides)
    return headers


def test_screen_event_meaningful_comparison_preserves_correlation(
    monkeypatch,
    caplog,
) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    previous = _jpeg_bytes()
    current = _jpeg_bytes()
    caplog.set_level(logging.INFO, logger=visual_observations.__name__)

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + current,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] == "12345678-1234-4234-8234-123456789abc"
    assert payload["previous_frame_id"] == 11
    assert payload["current_frame_id"] == 12
    assert payload["occurred_at"] == "2026-01-02T03:04:05Z"
    assert payload["change_score"] == 0.125
    assert payload["summary"] == "The visible form value changed."
    assert payload["event_id"]
    assert created["vision_observer"].requests == [
        (previous, current, "image/jpeg", "screen")
    ]
    assert "visual_change_detected" in caplog.text
    assert "visual_event_emitted" in caplog.text
    assert "The visible form value changed." not in caplog.text
    assert "JFIF" not in caplog.text
    assert "base64" not in caplog.text


def test_screen_event_persists_idempotently_by_conversation(monkeypatch) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    event = {
        "conversation_id": "conv_authoritative",
        "event_id": "87654321-4321-4321-8321-cba987654321",
        "session_id": "12345678-1234-4234-8234-123456789abc",
        "previous_frame_id": 11,
        "current_frame_id": 12,
        "occurred_at": "2026-01-02T03:04:05Z",
        "change_score": 0.125,
        "summary": "The visible form value changed.",
        "source": "screen",
        "time_in_call_secs": 31.25,
    }

    with TestClient(main.app) as client:
        first = client.put("/screen-observations/events", json=event)
        duplicate = client.put("/screen-observations/events", json=event)
        conflict = client.put(
            "/screen-observations/events",
            json={**event, "conversation_id": "conv_different"},
        )

    assert first.status_code == 200
    assert first.json()["status"] == "persisted"
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"
    assert conflict.status_code == 409
    assert len(created["postgres_client"].screen_observations) == 1
    stored = created["postgres_client"].screen_observations[0]
    assert stored["conversation_id"] == "conv_authoritative"
    assert stored["time_in_call_secs"] == 31.25


def test_screen_event_suppresses_non_meaningful_change(monkeypatch) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    created["vision_observer"].change = VisualChange(
        meaningful_change=False,
        summary=None,
    )
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + current,
        )

    assert response.status_code == 204
    assert response.content == b""
    assert created["vision_observer"].requests == [
        (previous, current, "image/jpeg", "screen")
    ]


def test_camera_event_reaches_the_model_as_camera(monkeypatch) -> None:
    """A camera pair must be analysed under the camera instructions, not the screen's."""
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    created["vision_observer"].change = VisualChange(
        meaningful_change=True,
        summary="The user removed the rear wheel and reached for the tire lever.",
    )
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(
                previous,
                current,
                **{"X-Visual-Source": "camera"},
            ),
            content=previous + current,
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "camera"
    assert payload["summary"] == (
        "The user removed the rear wheel and reached for the tire lever."
    )
    assert created["vision_observer"].requests == [
        (previous, current, "image/jpeg", "camera")
    ]


def test_visual_event_defaults_to_screen_without_the_header(monkeypatch) -> None:
    """An older browser sends no source header and still describes a screen."""
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + current,
        )

    assert response.status_code == 200
    assert response.json()["source"] == "screen"
    assert created["vision_observer"].requests[0][3] == "screen"


def test_visual_event_rejects_an_unknown_source(monkeypatch) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(
                previous,
                current,
                **{"X-Visual-Source": "webcam"},
            ),
            content=previous + current,
        )

    assert response.status_code == 422
    assert created["vision_observer"].requests == []


def test_camera_observation_is_persisted_with_its_source(monkeypatch) -> None:
    """The stored row must say camera, or distillation cannot tell them apart."""
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    event = {
        "conversation_id": "conv_authoritative",
        "event_id": "87654321-4321-4321-8321-cba987654322",
        "session_id": "12345678-1234-4234-8234-123456789abc",
        "source": "camera",
        "previous_frame_id": 11,
        "current_frame_id": 12,
        "occurred_at": "2026-01-02T03:04:05Z",
        "change_score": 0.42,
        "summary": "The user loosened the rear brake cable.",
    }

    with TestClient(main.app) as client:
        response = client.put("/screen-observations/events", json=event)

    assert response.status_code == 200
    stored = created["postgres_client"].screen_observations
    assert len(stored) == 1
    assert stored[0]["source"] == "camera"


def test_screen_event_rejects_invalid_input_before_model(monkeypatch) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        malformed_previous = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=(b"x" * len(previous)) + current,
        )
        malformed_current = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + (b"x" * len(current)),
        )
        mismatched_dimensions = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(
                previous,
                current,
                **{"X-Screen-Current-Width": "20"},
            ),
            content=previous + current,
        )
        malformed_metadata = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(
                previous,
                current,
                **{"X-Screen-Current-Frame-Id": "zero"},
            ),
            content=previous + current,
        )
        oversized = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(
                previous,
                current,
                **{
                    "X-Screen-Previous-Bytes": str(
                        visual_observations.MAX_IMAGE_BYTES + 1
                    )
                },
            ),
            content=previous + current,
        )

    assert malformed_previous.status_code == 422
    assert malformed_current.status_code == 422
    assert mismatched_dimensions.status_code == 422
    assert malformed_metadata.status_code == 422
    assert oversized.status_code == 413
    assert created["vision_observer"].requests == []


def test_screen_event_sanitizes_model_failure(monkeypatch, caplog) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    created["vision_observer"].error = RuntimeError("private provider details")
    previous = _jpeg_bytes()
    current = _jpeg_bytes()
    caplog.set_level(logging.INFO, logger=visual_observations.__name__)

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + current,
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "Vision model request failed."}
    assert "private provider details" not in response.text
    assert "private provider details" not in caplog.text


def test_screen_event_maps_timeout(monkeypatch) -> None:
    _, _, created = _install_lifecycle_fakes(monkeypatch)
    created["vision_observer"].delay = 0.01
    monkeypatch.setattr(visual_observations, "VLM_TIMEOUT_SECONDS", 0.001)
    previous = _jpeg_bytes()
    current = _jpeg_bytes()

    with TestClient(main.app) as client:
        response = client.post(
            "/screen-observations",
            headers=_screen_pair_headers(previous, current),
            content=previous + current,
        )

    assert response.status_code == 504
    assert response.json() == {"detail": "Vision model timed out."}
